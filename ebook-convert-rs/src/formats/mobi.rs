//! MOBI/AZW/PRC reader and writer.
//!
//! MOBI is a binary format built on PalmDB:
//!   PalmDB Header (78 bytes) → Record list → MOBI Header → EXTH metadata → Compressed HTML
//!
//! Record 0 contains the MOBI header + EXTH records.
//! Subsequent records contain PalmDOC-compressed (LZ77) or Huffman-compressed HTML.
//! The last records may contain FLIS, FCIS, EOF markers, and cover images.
//!
//! AZW3/KF8 is a dual-format file: MOBI (for old Kindles) + KF8 (HTML5-based).
//! We read the KF8 portion when available, falling back to MOBI.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::Path;

use crate::pipeline::document::OebDocument;
use crate::pipeline::metadata::Metadata;

// ── Constants ───────────────────────────────────────────────────────────

const PALMDOC_COMPRESSION: u16 = 2;
const HUFF_COMPRESSION: u16 = 17480;
const NO_COMPRESSION: u16 = 1;

// EXTH record types
const EXTH_AUTHOR: u32 = 100;
const EXTH_PUBLISHER: u32 = 101;
const EXTH_DESCRIPTION: u32 = 103;
const EXTH_ISBN: u32 = 104;
const EXTH_SUBJECT: u32 = 105;
const EXTH_PUBDATE: u32 = 106;
const EXTH_ASIN: u32 = 113;
const EXTH_LANGUAGE: u32 = 524;
const EXTH_COVER_OFFSET: u32 = 201;
const EXTH_THUMB_OFFSET: u32 = 202;
const EXTH_KF8_BOUNDARY: u32 = 121;

// ── PalmDB Header ───────────────────────────────────────────────────────

#[derive(Debug)]
struct PalmHeader {
    name: String,
    num_records: u16,
    record_offsets: Vec<u32>,
}

fn read_palm_header(data: &[u8]) -> Result<PalmHeader> {
    if data.len() < 78 {
        anyhow::bail!("File too small for PalmDB header");
    }

    let name = String::from_utf8_lossy(&data[0..32])
        .trim_end_matches('\0')
        .to_string();
    let num_records = u16::from_be_bytes([data[76], data[77]]);

    let mut offsets = Vec::with_capacity(num_records as usize);
    for i in 0..num_records as usize {
        let base = 78 + i * 8;
        if base + 4 > data.len() {
            break;
        }
        let offset = u32::from_be_bytes([data[base], data[base + 1], data[base + 2], data[base + 3]]);
        offsets.push(offset);
    }

    Ok(PalmHeader {
        name,
        num_records,
        record_offsets: offsets,
    })
}

// ── MOBI Header ─────────────────────────────────────────────────────────

#[derive(Debug)]
struct MobiHeader {
    compression: u16,
    text_length: u32,
    record_count: u16,
    record_size: u16,
    encoding: u32, // 1252 = CP1252, 65001 = UTF-8
    mobi_type: u32,
    first_image_record: u32,
    exth_flags: u32,
    title: String,
    kf8_boundary: Option<u32>,
    huff_rec: u32,
    huff_cnt: u32,
}

fn read_mobi_header(record0: &[u8]) -> Result<MobiHeader> {
    // LP#1179144: KindleGen 2.9 generates KF8 with header length 264.
    // Accept any record0 >= 132 bytes (minimum for fields we need).
    if record0.len() < 132 {
        anyhow::bail!("Record 0 too small for MOBI header ({} bytes, need 132)", record0.len());
    }

    let compression = u16::from_be_bytes([record0[0], record0[1]]);
    let text_length = u32::from_be_bytes([record0[4], record0[5], record0[6], record0[7]]);
    let record_count = u16::from_be_bytes([record0[8], record0[9]]);
    let record_size = u16::from_be_bytes([record0[10], record0[11]]);
    let encoding = u32::from_be_bytes([record0[28], record0[29], record0[30], record0[31]]);
    let mobi_type = u32::from_be_bytes([record0[24], record0[25], record0[26], record0[27]]);

    // These fields may be absent in short headers — read with bounds checks
    let first_image_record = read_u32_be_safe(record0, 108).unwrap_or(0xFFFFFFFF);
    let exth_flags = read_u32_be_safe(record0, 128).unwrap_or(0);

    // Title from MOBI header (offsets 84-91)
    let title_offset = read_u32_be_safe(record0, 84).unwrap_or(0) as usize;
    let title_length = read_u32_be_safe(record0, 88).unwrap_or(0) as usize;
    let title = if title_offset > 0 && title_length > 0
        && title_offset.checked_add(title_length).is_some_and(|end| end <= record0.len())
    {
        String::from_utf8_lossy(&record0[title_offset..title_offset + title_length]).to_string()
    } else {
        String::new()
    };

    // HUFF/CDIC record indices (offsets 112-119)
    let huff_rec = read_u32_be_safe(record0, 112).unwrap_or(0);
    let huff_cnt = read_u32_be_safe(record0, 116).unwrap_or(0);

    Ok(MobiHeader {
        compression,
        text_length,
        record_count,
        record_size,
        encoding,
        mobi_type,
        first_image_record,
        exth_flags,
        title,
        kf8_boundary: None,
        huff_rec,
        huff_cnt,
    })
}

/// Read a big-endian u32 at `offset` if within bounds.
fn read_u32_be_safe(data: &[u8], offset: usize) -> Option<u32> {
    if offset + 4 <= data.len() {
        Some(u32::from_be_bytes([data[offset], data[offset + 1], data[offset + 2], data[offset + 3]]))
    } else {
        None
    }
}

// ── EXTH Records ────────────────────────────────────────────────────────

fn read_exth(record0: &[u8]) -> HashMap<u32, Vec<String>> {
    let mut map: HashMap<u32, Vec<String>> = HashMap::new();

    // Find EXTH header — starts after MOBI header, identified by "EXTH" magic
    let exth_start = record0
        .windows(4)
        .position(|w| w == b"EXTH");

    let start = match exth_start {
        Some(pos) => pos,
        None => return map,
    };

    if start + 12 > record0.len() {
        return map;
    }

    let _header_length = u32::from_be_bytes([
        record0[start + 4], record0[start + 5],
        record0[start + 6], record0[start + 7],
    ]);
    let record_count = u32::from_be_bytes([
        record0[start + 8], record0[start + 9],
        record0[start + 10], record0[start + 11],
    ]);

    // Cap record count to prevent infinite loops on malformed data
    let record_count = record_count.min(1000);

    let mut pos = start + 12;
    for _ in 0..record_count {
        // Each EXTH record is independent — a bad one shouldn't kill the rest.
        // Calibre wraps each record parse in its own try/except.
        if pos + 8 > record0.len() {
            break;
        }
        let rec_type = u32::from_be_bytes([
            record0[pos], record0[pos + 1], record0[pos + 2], record0[pos + 3],
        ]);
        let rec_len = u32::from_be_bytes([
            record0[pos + 4], record0[pos + 5], record0[pos + 6], record0[pos + 7],
        ]) as usize;

        if rec_len < 8 || pos + rec_len > record0.len() {
            // Skip this record but try to continue if possible
            if rec_len >= 8 {
                pos += rec_len;
                continue;
            }
            break;
        }

        let value_bytes = &record0[pos + 8..pos + rec_len];
        let value = String::from_utf8_lossy(value_bytes).to_string();
        map.entry(rec_type).or_default().push(value);

        pos += rec_len;
    }

    map
}

// ── PalmDOC LZ77 Decompression ──────────────────────────────────────────

fn decompress_palmdoc(data: &[u8]) -> Vec<u8> {
    let mut output = Vec::with_capacity(data.len() * 2);
    let mut i = 0;

    while i < data.len() {
        let byte = data[i];
        i += 1;

        match byte {
            0x00 => output.push(0),
            0x01..=0x08 => {
                // Copy next N bytes literally
                let count = byte as usize;
                for _ in 0..count {
                    if i < data.len() {
                        output.push(data[i]);
                        i += 1;
                    }
                }
            }
            0x09..=0x7F => {
                // Literal byte
                output.push(byte);
            }
            0x80..=0xBF => {
                // LZ77 back-reference: 2 bytes encode distance + length
                if i >= data.len() {
                    break;
                }
                let next = data[i] as u16;
                i += 1;
                let combined = ((byte as u16) << 8) | next;
                let distance = ((combined >> 3) & 0x7FF) as usize;
                let length = ((combined & 0x07) + 3) as usize;

                if distance > 0 && distance <= output.len() {
                    let start = output.len() - distance;
                    for j in 0..length {
                        let idx = start + (j % distance);
                        if idx < output.len() {
                            output.push(output[idx]);
                        }
                    }
                }
            }
            0xC0..=0xFF => {
                // Space + char
                output.push(b' ');
                output.push(byte ^ 0x80);
            }
        }
    }

    output
}

// ── Huffman/CDIC Decompression ──────────────────────────────────────────
//
// MOBI files may use Huffman/CDIC compression (compression type 17480).
// The HUFF record contains two lookup tables:
//   - table1 (256 entries at off1): maps first byte → (codelen, terminal, maxcode)
//   - table2 (64 entries at off2): mincode/maxcode pairs for code lengths 1..32
// The CDIC records contain the dictionary of phrases indexed by code value.
//
// Decompression reads a bitstream, looks up codes in table1/table2,
// resolves the dictionary index, and recursively expands non-terminal phrases.

/// Parsed HUFF record tables.
struct HuffTables {
    /// table1: 256 entries, each (codelen, is_terminal, maxcode_shifted)
    table1: Vec<(u8, bool, u32)>,
    /// Minimum code value for each code length (index 0 unused, 1..=32)
    mincode: Vec<u64>,
    /// Maximum code value for each code length (index 0 unused, 1..=32)
    maxcode: Vec<u64>,
    /// Dictionary entries: (phrase_bytes, is_terminal)
    dictionary: Vec<(Vec<u8>, bool)>,
}

impl HuffTables {
    /// Parse the HUFF record to build table1 and table2.
    fn load_huff(huff: &[u8]) -> Result<Self> {
        if huff.len() < 24 || &huff[0..4] != b"HUFF" {
            anyhow::bail!("Invalid HUFF record header");
        }
        let off1 = u32::from_be_bytes([huff[8], huff[9], huff[10], huff[11]]) as usize;
        let off2 = u32::from_be_bytes([huff[12], huff[13], huff[14], huff[15]]) as usize;

        // table1: 256 x u32 at off1
        if off1 + 256 * 4 > huff.len() {
            anyhow::bail!("HUFF table1 extends past record");
        }
        let mut table1 = Vec::with_capacity(256);
        for i in 0..256 {
            let base = off1 + i * 4;
            let v = u32::from_be_bytes([huff[base], huff[base + 1], huff[base + 2], huff[base + 3]]);
            let codelen = (v & 0x1F) as u8;
            let term = (v & 0x80) != 0;
            let maxcode_raw = v >> 8;
            // Shift maxcode to align at bit 31 for comparison with 32-bit code window
            let maxcode_shifted = ((maxcode_raw as u64 + 1) << (32 - codelen as u32)) - 1;
            table1.push((codelen, term, maxcode_shifted as u32));
        }

        // table2: 64 x u32 at off2 → 32 pairs of (mincode, maxcode)
        if off2 + 64 * 4 > huff.len() {
            anyhow::bail!("HUFF table2 extends past record");
        }
        let mut mincode = vec![0u64; 33]; // index 0..=32
        let mut maxcode = vec![0u64; 33];
        for codelen in 1..=32usize {
            let idx = (codelen - 1) * 2;
            let base = off2 + idx * 4;
            let min_raw = u32::from_be_bytes([huff[base], huff[base + 1], huff[base + 2], huff[base + 3]]);
            let max_raw = u32::from_be_bytes([huff[base + 4], huff[base + 5], huff[base + 6], huff[base + 7]]);
            mincode[codelen] = (min_raw as u64) << (32 - codelen as u32);
            maxcode[codelen] = (((max_raw as u64) + 1) << (32 - codelen as u32)) - 1;
        }

        Ok(HuffTables {
            table1,
            mincode,
            maxcode,
            dictionary: Vec::new(),
        })
    }

    /// Load a CDIC record, appending its phrases to the dictionary.
    fn load_cdic(&mut self, cdic: &[u8]) -> Result<()> {
        if cdic.len() < 16 || &cdic[0..4] != b"CDIC" {
            anyhow::bail!("Invalid CDIC record header");
        }
        let phrases = u32::from_be_bytes([cdic[8], cdic[9], cdic[10], cdic[11]]) as usize;
        let bits = u32::from_be_bytes([cdic[12], cdic[13], cdic[14], cdic[15]]) as usize;
        let n = (1usize << bits).min(phrases.saturating_sub(self.dictionary.len()));

        // Offset table starts at byte 16, n x u16
        if 16 + n * 2 > cdic.len() {
            anyhow::bail!("CDIC offset table extends past record");
        }

        for i in 0..n {
            let off_pos = 16 + i * 2;
            let off = u16::from_be_bytes([cdic[off_pos], cdic[off_pos + 1]]) as usize;
            let data_pos = 16 + off;
            if data_pos + 2 > cdic.len() {
                self.dictionary.push((Vec::new(), true));
                continue;
            }
            let blen = u16::from_be_bytes([cdic[data_pos], cdic[data_pos + 1]]);
            let slice_len = (blen & 0x7FFF) as usize;
            let is_terminal = (blen & 0x8000) != 0;
            let start = data_pos + 2;
            let end = (start + slice_len).min(cdic.len());
            self.dictionary.push((cdic[start..end].to_vec(), is_terminal));
        }
        Ok(())
    }

    /// Decompress a single text record using the loaded HUFF/CDIC tables.
    fn unpack(&self, data: &[u8]) -> Result<Vec<u8>> {
        let mut bits_left = data.len() as i64 * 8;
        // Pad data so we can always read 8 bytes ahead
        let mut padded = data.to_vec();
        padded.extend_from_slice(&[0u8; 8]);

        let mut pos = 0usize;
        let mut x = read_u64_be(&padded, pos);
        let mut n: i32 = 32;
        let mut result = Vec::new();

        loop {
            if n <= 0 {
                pos += 4;
                x = read_u64_be(&padded, pos);
                n += 32;
            }
            let code = ((x >> n as u32) & 0xFFFF_FFFF) as u32;

            // Fast lookup via table1 using top 8 bits
            let (mut codelen, term, t1_maxcode) = self.table1[(code >> 24) as usize];

            if !term {
                // Not terminal in table1 — walk table2 to find correct code length
                let mut cl = codelen as usize;
                loop {
                    cl += 1;
                    if cl > 32 || (code as u64) < self.mincode[cl] {
                        break;
                    }
                }
                codelen = cl.min(32) as u8;
            }

            n -= codelen as i32;
            bits_left -= codelen as i64;
            if bits_left < 0 {
                break;
            }

            // Compute dictionary index: (maxcode - code) >> (32 - codelen)
            let mc = if term {
                t1_maxcode as u64
            } else {
                self.maxcode[codelen as usize]
            };
            let r = (mc.wrapping_sub(code as u64) >> (32 - codelen as u32)) as usize;

            if r >= self.dictionary.len() {
                anyhow::bail!("HUFF/CDIC dictionary index {} out of range (len={})", r, self.dictionary.len());
            }

            let (ref phrase, is_term) = self.dictionary[r];
            if is_term {
                result.extend_from_slice(phrase);
            } else {
                // Recursive decompression of non-terminal phrase
                let expanded = self.unpack(phrase)?;
                result.extend_from_slice(&expanded);
            }
        }

        Ok(result)
    }
}

/// Read a big-endian u64 from a byte slice at the given offset.
fn read_u64_be(data: &[u8], pos: usize) -> u64 {
    if pos + 8 > data.len() {
        return 0;
    }
    u64::from_be_bytes([
        data[pos], data[pos + 1], data[pos + 2], data[pos + 3],
        data[pos + 4], data[pos + 5], data[pos + 6], data[pos + 7],
    ])
}

// ── Reader ──────────────────────────────────────────────────────────────

/// Read a MOBI/AZW/PRC file into an OEB document.
pub fn read(path: &Path) -> Result<OebDocument> {
    let data = std::fs::read(path).context("Failed to read MOBI file")?;
    let palm = read_palm_header(&data)?;

    // Get record 0 (MOBI header + EXTH)
    if palm.record_offsets.is_empty() {
        anyhow::bail!("MOBI file has no records");
    }
    let rec0_start = palm.record_offsets[0] as usize;
    let rec0_end = if palm.record_offsets.len() > 1 {
        palm.record_offsets[1] as usize
    } else {
        data.len()
    };
    if rec0_start >= data.len() || rec0_end > data.len() || rec0_start >= rec0_end {
        anyhow::bail!(
            "Record 0 offsets out of bounds: start={rec0_start}, end={rec0_end}, file_len={}",
            data.len()
        );
    }
    let record0 = &data[rec0_start..rec0_end];

    let mut mobi = read_mobi_header(record0)?;

    // DRM detection — check encryption type at offset 12 in record 0
    let encryption = if record0.len() > 13 {
        u16::from_be_bytes([record0[12], record0[13]])
    } else {
        0
    };
    if encryption != 0 {
        anyhow::bail!(
            "This MOBI file has DRM encryption (type {}). \
             DRM-protected files cannot be converted. \
             Use Calibre with appropriate plugins for DRM handling.",
            encryption
        );
    }

    let exth = read_exth(record0);

    // Check for KF8 boundary — dual-format files have a MOBI6 section
    // followed by a KF8 section starting at the boundary record.
    if let Some(boundary_vals) = exth.get(&EXTH_KF8_BOUNDARY) {
        if let Some(val) = boundary_vals.first() {
            if let Ok(boundary) = val.trim_end_matches('\0').parse::<u32>() {
                if boundary < palm.num_records as u32 && boundary != 0xFFFFFFFF {
                    mobi.kf8_boundary = Some(boundary);
                }
            }
        }
    }

    // If KF8 boundary exists, try to read the KF8 section instead
    if let Some(boundary) = mobi.kf8_boundary {
        match read_kf8_section(&data, &palm, boundary as usize) {
            Ok(doc) => {
                tracing::info!("Read KF8 section from dual-format MOBI");
                return Ok(doc);
            }
            Err(e) => {
                tracing::warn!("KF8 section parse failed, falling back to MOBI6: {e}");
            }
        }
    }

    // Build metadata from MOBI6 section
    let mut metadata = Metadata::new(if mobi.title.is_empty() {
        &palm.name
    } else {
        &mobi.title
    });

    if let Some(authors) = exth.get(&EXTH_AUTHOR) {
        // Amazon MOBI files store authors as "LastName, FirstName" — normalize
        metadata.authors = authors.iter().map(|a| normalize_author(a)).collect();
    }
    if let Some(v) = exth.get(&EXTH_PUBLISHER) {
        metadata.publisher = v.first().cloned();
    }
    if let Some(v) = exth.get(&EXTH_DESCRIPTION) {
        metadata.description = v.first().cloned();
    }
    if let Some(v) = exth.get(&EXTH_ISBN) {
        metadata.isbn = v.first().cloned();
    }
    if let Some(v) = exth.get(&EXTH_SUBJECT) {
        metadata.tags = v.clone();
    }
    if let Some(v) = exth.get(&EXTH_PUBDATE) {
        metadata.pubdate = v.first().cloned();
    }
    if let Some(v) = exth.get(&EXTH_LANGUAGE) {
        metadata.language = v.first().cloned();
    }
    if let Some(v) = exth.get(&EXTH_ASIN) {
        if let Some(asin) = v.first() {
            metadata.identifiers.insert("asin".into(), asin.clone());
        }
    }

    // Decompress text records
    let mut html_bytes = Vec::new();
    let text_records = mobi.record_count as usize;

    // Cap record count to prevent memory exhaustion from malicious files
    // KindleGen uses 64512 (0x10000 - 1024) as the PDB record limit, not 65536.
    const MAX_TEXT_RECORDS: usize = 64512;
    const MAX_DECOMPRESSED_SIZE: usize = 256 * 1024 * 1024; // 256 MB
    if text_records > MAX_TEXT_RECORDS {
        anyhow::bail!("MOBI text record count {} exceeds limit {}", text_records, MAX_TEXT_RECORDS);
    }

    // Load HUFF/CDIC tables if needed
    let huff_tables = if mobi.compression == HUFF_COMPRESSION && mobi.huff_rec > 0 && mobi.huff_cnt > 0 {
        let huff_data = get_record(&data, &palm, mobi.huff_rec as usize)
            .ok_or_else(|| anyhow::anyhow!("HUFF record {} not found", mobi.huff_rec))?;
        let mut tables = HuffTables::load_huff(huff_data)?;
        for i in 1..mobi.huff_cnt {
            let cdic_idx = mobi.huff_rec as usize + i as usize;
            let cdic_data = get_record(&data, &palm, cdic_idx)
                .ok_or_else(|| anyhow::anyhow!("CDIC record {} not found", cdic_idx))?;
            tables.load_cdic(cdic_data)?;
        }
        Some(tables)
    } else {
        None
    };

    for i in 1..=text_records {
        if i >= palm.record_offsets.len() {
            break;
        }
        let start = palm.record_offsets[i] as usize;
        let end = if i + 1 < palm.record_offsets.len() {
            palm.record_offsets[i + 1] as usize
        } else {
            data.len()
        };

        if start >= data.len() || end > data.len() || start >= end {
            if crate::pipeline::is_lenient() {
                tracing::warn!("Skipping record {i}: offsets out of bounds (start={start}, end={end})");
                continue;
            }
            break;
        }

        let record = &data[start..end];
        match mobi.compression {
            NO_COMPRESSION => html_bytes.extend_from_slice(record),
            PALMDOC_COMPRESSION => {
                let decompressed = decompress_palmdoc(record);
                if decompressed.is_empty() && !record.is_empty() && crate::pipeline::is_lenient() {
                    tracing::warn!("Record {i}: PalmDOC decompression produced empty output, skipping");
                    continue;
                }
                html_bytes.extend(decompressed);
            }
            HUFF_COMPRESSION => {
                if let Some(ref tables) = huff_tables {
                    match tables.unpack(record) {
                        Ok(decompressed) => html_bytes.extend(decompressed),
                        Err(e) => {
                            tracing::warn!("HUFF/CDIC decompression failed for record {i}: {e}");
                            html_bytes.extend_from_slice(record);
                        }
                    }
                } else {
                    tracing::warn!("HUFF compression but no HUFF/CDIC tables loaded");
                    html_bytes.extend_from_slice(record);
                }
            }
            _ => {
                tracing::warn!("Unknown compression type: {}", mobi.compression);
                html_bytes.extend_from_slice(record);
            }
        }

        if html_bytes.len() > MAX_DECOMPRESSED_SIZE {
            anyhow::bail!(
                "Decompressed text exceeds {} MB limit — possible decompression bomb",
                MAX_DECOMPRESSED_SIZE / (1024 * 1024)
            );
        }
    }

    // Decode text
    let html_text = if mobi.encoding == 65001 {
        String::from_utf8_lossy(&html_bytes).to_string()
    } else {
        // CP1252 fallback — map high bytes to Unicode
        html_bytes.iter().map(|&b| {
            if b < 128 { b as char } else { cp1252_to_char(b) }
        }).collect()
    };

    // Extract cover image from image records
    let mut doc = OebDocument::new();
    doc.metadata = metadata;

    if let Some(cover_offsets) = exth.get(&EXTH_COVER_OFFSET) {
        if let Some(offset_str) = cover_offsets.first() {
            if let Ok(offset) = offset_str.trim_end_matches('\0').parse::<u32>() {
                let img_record = mobi.first_image_record + offset;
                if let Some(img_data) = get_record(&data, &palm, img_record as usize) {
                    if img_data.starts_with(&[0xFF, 0xD8]) {
                        doc.add_image("cover.jpg", img_data.to_vec(), "image/jpeg");
                        doc.metadata.cover_image = Some("cover.jpg".into());
                    } else if img_data.starts_with(b"\x89PNG") {
                        doc.add_image("cover.png", img_data.to_vec(), "image/png");
                        doc.metadata.cover_image = Some("cover.png".into());
                    }
                }
            }
        }
    }

    // Add the HTML content
    doc.add_html("content.xhtml", ensure_xhtml(&html_text));

    tracing::info!(
        "Read MOBI: {} bytes text, {} compression, encoding {}",
        html_bytes.len(),
        mobi.compression,
        mobi.encoding
    );

    Ok(doc)
}

// ── KF8 Dual-Format Parsing ────────────────────────────────────────────
//
// AZW3/KF8 dual-format files contain two book sections:
//   1. MOBI6 section (records 0..boundary-1) — legacy format
//   2. KF8 section (records boundary..end) — HTML5-based format
//
// The KF8 section has its own record 0 with MOBI header, EXTH, and
// compressed HTML5 content. We prefer KF8 when available because it
// preserves richer formatting.

/// Read the KF8 section from a dual-format MOBI file.
fn read_kf8_section(data: &[u8], palm: &PalmHeader, boundary: usize) -> Result<OebDocument> {
    // The KF8 section starts at record `boundary`. Its record 0 is at that index.
    let kf8_rec0 = get_record(data, palm, boundary)
        .ok_or_else(|| anyhow::anyhow!("KF8 boundary record {} not found", boundary))?;

    let kf8_mobi = read_mobi_header(kf8_rec0)?;
    let kf8_exth = read_exth(kf8_rec0);

    // DRM check on KF8 section
    let encryption = if kf8_rec0.len() > 13 {
        u16::from_be_bytes([kf8_rec0[12], kf8_rec0[13]])
    } else {
        0
    };
    if encryption != 0 {
        anyhow::bail!("KF8 section has DRM encryption (type {})", encryption);
    }

    // Build metadata
    let mut metadata = Metadata::new(if kf8_mobi.title.is_empty() {
        "Untitled"
    } else {
        &kf8_mobi.title
    });

    if let Some(authors) = kf8_exth.get(&EXTH_AUTHOR) {
        metadata.authors = authors.iter().map(|a| normalize_author(a)).collect();
    }
    if let Some(v) = kf8_exth.get(&EXTH_PUBLISHER) {
        metadata.publisher = v.first().cloned();
    }
    if let Some(v) = kf8_exth.get(&EXTH_DESCRIPTION) {
        metadata.description = v.first().cloned();
    }
    if let Some(v) = kf8_exth.get(&EXTH_ISBN) {
        metadata.isbn = v.first().cloned();
    }
    if let Some(v) = kf8_exth.get(&EXTH_SUBJECT) {
        metadata.tags = v.clone();
    }
    if let Some(v) = kf8_exth.get(&EXTH_LANGUAGE) {
        metadata.language = v.first().cloned();
    }

    // Load HUFF/CDIC tables for KF8 section if needed
    let huff_tables = if kf8_mobi.compression == HUFF_COMPRESSION && kf8_mobi.huff_rec > 0 && kf8_mobi.huff_cnt > 0 {
        let abs_huff = boundary + kf8_mobi.huff_rec as usize;
        let huff_data = get_record(data, palm, abs_huff)
            .ok_or_else(|| anyhow::anyhow!("KF8 HUFF record not found"))?;
        let mut tables = HuffTables::load_huff(huff_data)?;
        for i in 1..kf8_mobi.huff_cnt {
            let cdic_idx = abs_huff + i as usize;
            let cdic_data = get_record(data, palm, cdic_idx)
                .ok_or_else(|| anyhow::anyhow!("KF8 CDIC record not found"))?;
            tables.load_cdic(cdic_data)?;
        }
        Some(tables)
    } else {
        None
    };

    // Decompress KF8 text records (relative to boundary)
    let mut html_bytes = Vec::new();
    let text_records = kf8_mobi.record_count as usize;

    for i in 1..=text_records {
        let abs_idx = boundary + i;
        let record = match get_record(data, palm, abs_idx) {
            Some(r) => r,
            None => break,
        };

        match kf8_mobi.compression {
            NO_COMPRESSION => html_bytes.extend_from_slice(record),
            PALMDOC_COMPRESSION => html_bytes.extend(decompress_palmdoc(record)),
            HUFF_COMPRESSION => {
                if let Some(ref tables) = huff_tables {
                    match tables.unpack(record) {
                        Ok(d) => html_bytes.extend(d),
                        Err(e) => {
                            tracing::warn!("KF8 HUFF decompression failed: {e}");
                            html_bytes.extend_from_slice(record);
                        }
                    }
                } else {
                    html_bytes.extend_from_slice(record);
                }
            }
            _ => html_bytes.extend_from_slice(record),
        }
    }

    let html_text = if kf8_mobi.encoding == 65001 {
        String::from_utf8_lossy(&html_bytes).to_string()
    } else {
        html_bytes.iter().map(|&b| {
            if b < 128 { b as char } else { cp1252_to_char(b) }
        }).collect()
    };

    let mut doc = OebDocument::new();
    doc.metadata = metadata;

    // Extract cover from the MOBI6 section's image records (shared between sections)
    // The first_image_record in KF8 is relative to the KF8 boundary
    let abs_first_img = boundary + kf8_mobi.first_image_record as usize;
    if let Some(cover_offsets) = kf8_exth.get(&EXTH_COVER_OFFSET) {
        if let Some(offset_str) = cover_offsets.first() {
            if let Ok(offset) = offset_str.trim_end_matches('\0').parse::<u32>() {
                let img_record = abs_first_img + offset as usize;
                if let Some(img_data) = get_record(data, palm, img_record) {
                    if img_data.starts_with(&[0xFF, 0xD8]) {
                        doc.add_image("cover.jpg", img_data.to_vec(), "image/jpeg");
                        doc.metadata.cover_image = Some("cover.jpg".into());
                    } else if img_data.starts_with(b"\x89PNG") {
                        doc.add_image("cover.png", img_data.to_vec(), "image/png");
                        doc.metadata.cover_image = Some("cover.png".into());
                    }
                }
            }
        }
    }

    doc.add_html("content.xhtml", ensure_xhtml(&html_text));

    tracing::info!(
        "Read KF8: {} bytes text, {} compression, encoding {}",
        html_bytes.len(),
        kf8_mobi.compression,
        kf8_mobi.encoding
    );

    Ok(doc)
}

// ── Writer ──────────────────────────────────────────────────────────────

/// Write an OEB document as a MOBI file.
///
/// Generates a PalmDOC-compressed MOBI with EXTH metadata,
/// embedded images, and proper FLIS/FCIS/EOF trailing records.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    // Collect all HTML into one string (MOBI is single-HTML)
    let mut html = String::new();
    for name in &doc.spine {
        if let Some(content) = doc.html_files.get(name) {
            html.push_str(content);
        }
    }

    let html_bytes = html.as_bytes();
    let compressed_records = compress_palmdoc(html_bytes);
    let record_count = compressed_records.len() as u16;

    // Collect images in order
    let image_records: Vec<(&String, &Vec<u8>)> = doc.images.iter()
        .filter(|(_, data)| !data.is_empty())
        .collect();
    let first_image_record = if image_records.is_empty() {
        0xFFFFFFFFu32
    } else {
        (1 + record_count as u32) // after record 0 + text records
    };

    // Build EXTH records (with cover offset if we have images)
    let cover_offset = if !image_records.is_empty() { Some(0u32) } else { None };
    let exth = build_exth(&doc.metadata, cover_offset);

    // Build MOBI header (record 0)
    let record0 = build_record0(
        html_bytes.len() as u32,
        record_count,
        &exth,
        &doc.metadata.title,
        first_image_record,
    );

    // FLIS record (fixed)
    let flis: Vec<u8> = vec![
        0x46, 0x4C, 0x49, 0x53, // "FLIS"
        0x00, 0x00, 0x00, 0x08, // fixed length
        0x00, 0x41, 0x00, 0x00, // fixed
        0x00, 0x00, 0x00, 0x00, // fixed
        0xFF, 0xFF, 0xFF, 0xFF, // fixed
        0x00, 0x00, 0x00, 0x01, // fixed
        0x00, 0x00, 0x00, 0x03, // fixed
        0x00, 0x00, 0x00, 0x03, // fixed
        0x00, 0x00, 0x00, 0x01, // fixed
    ];

    // FCIS record
    let text_len_bytes = (html_bytes.len() as u32).to_be_bytes();
    let mut fcis: Vec<u8> = vec![
        0x46, 0x43, 0x49, 0x53, // "FCIS"
        0x00, 0x00, 0x00, 0x14, // fixed length
        0x00, 0x00, 0x00, 0x10, // fixed
    ];
    fcis.extend_from_slice(&text_len_bytes);
    fcis.extend_from_slice(&[
        0x00, 0x00, 0x00, 0x00, // fixed
        0x00, 0x00, 0x00, 0x20, // fixed
        0x00, 0x00, 0x00, 0x08, // fixed
        0x00, 0x01, 0x00, 0x01, // fixed
        0x00, 0x00, 0x00, 0x00, // fixed
    ]);

    // EOF record
    let eof: Vec<u8> = vec![0xE9, 0x8E, 0x0D, 0x0A];

    // Calculate total records: record0 + text + images + FLIS + FCIS + EOF
    let total_records = 1 + record_count as usize + image_records.len() + 3;

    // Calculate offsets
    let header_size = 78 + (total_records * 8);
    let mut offsets: Vec<u32> = Vec::new();
    let mut current_offset = header_size as u32;

    // Record 0
    offsets.push(current_offset);
    current_offset += record0.len() as u32;

    // Text records
    for rec in &compressed_records {
        offsets.push(current_offset);
        current_offset += rec.len() as u32;
    }

    // Image records
    for (_, data) in &image_records {
        offsets.push(current_offset);
        current_offset += data.len() as u32;
    }

    // FLIS, FCIS, EOF
    offsets.push(current_offset);
    current_offset += flis.len() as u32;
    offsets.push(current_offset);
    current_offset += fcis.len() as u32;
    offsets.push(current_offset);

    // Write file
    let mut output = Vec::with_capacity(current_offset as usize + eof.len());

    // PalmDB header (78 bytes)
    let mut name_bytes = [0u8; 32];
    let title_bytes = doc.metadata.title.as_bytes();
    let copy_len = title_bytes.len().min(31);
    name_bytes[..copy_len].copy_from_slice(&title_bytes[..copy_len]);
    output.extend_from_slice(&name_bytes);       // 0-31: name
    output.extend_from_slice(&[0u8; 2]);         // 32-33: attributes
    output.extend_from_slice(&[0u8; 2]);         // 34-35: version
    output.extend_from_slice(&[0u8; 4]);         // 36-39: creation date
    output.extend_from_slice(&[0u8; 4]);         // 40-43: modification date
    output.extend_from_slice(&[0u8; 4]);         // 44-47: backup date
    output.extend_from_slice(&[0u8; 4]);         // 48-51: modification number
    output.extend_from_slice(&[0u8; 4]);         // 52-55: app info offset
    output.extend_from_slice(&[0u8; 4]);         // 56-59: sort info offset
    output.extend_from_slice(b"BOOK");           // 60-63: type
    output.extend_from_slice(b"MOBI");           // 64-67: creator
    output.extend_from_slice(&[0u8; 4]);         // 68-71: unique ID seed
    output.extend_from_slice(&[0u8; 4]);         // 72-75: next record list
    output.extend_from_slice(&(total_records as u16).to_be_bytes()); // 76-77: num records

    // Record offset table (8 bytes per record: 4 offset + 1 attributes + 3 unique ID)
    for (i, offset) in offsets.iter().enumerate() {
        output.extend_from_slice(&offset.to_be_bytes());
        output.push(0); // attributes
        output.push(((i >> 16) & 0xFF) as u8); // unique ID (3 bytes)
        output.push(((i >> 8) & 0xFF) as u8);
        output.push((i & 0xFF) as u8);
    }

    // Record 0 (MOBI header + EXTH)
    output.extend_from_slice(&record0);

    // Text records
    for rec in &compressed_records {
        output.extend_from_slice(rec);
    }

    // Image records
    for (_, data) in &image_records {
        output.extend_from_slice(data);
    }

    // FLIS, FCIS, EOF
    output.extend_from_slice(&flis);
    output.extend_from_slice(&fcis);
    output.extend_from_slice(&eof);

    std::fs::write(path, output)?;
    tracing::info!(
        "Wrote MOBI: {} text records, {} images, {} total records",
        record_count, image_records.len(), total_records
    );
    Ok(())
}

// ── MOBI Record 0 Builder ───────────────────────────────────────────────

fn build_record0(text_length: u32, record_count: u16, exth: &[u8], title: &str, first_image_record: u32) -> Vec<u8> {
    let mut rec = Vec::new();

    // PalmDOC header (16 bytes: offsets 0–15)
    rec.extend_from_slice(&PALMDOC_COMPRESSION.to_be_bytes()); // 0-1: compression
    rec.extend_from_slice(&[0, 0]);                            // 2-3: unused
    rec.extend_from_slice(&text_length.to_be_bytes());         // 4-7: text length
    rec.extend_from_slice(&record_count.to_be_bytes());        // 8-9: record count
    rec.extend_from_slice(&4096u16.to_be_bytes());             // 10-11: record size
    rec.extend_from_slice(&[0, 0]);                            // 12-13: encryption (none)
    rec.extend_from_slice(&[0, 0]);                            // 14-15: unused

    // MOBI header (starts at offset 16)
    rec.extend_from_slice(b"MOBI");                            // 16-19: magic
    let mobi_header_length = 232u32;
    rec.extend_from_slice(&mobi_header_length.to_be_bytes());  // 20-23: header length
    rec.extend_from_slice(&2u32.to_be_bytes());                // 24-27: MOBI type (book)
    rec.extend_from_slice(&65001u32.to_be_bytes());            // 28-31: encoding (UTF-8)
    rec.extend_from_slice(&[0xFF; 4]);                         // 32-35: unique ID
    rec.extend_from_slice(&8u32.to_be_bytes());                // 36-39: file version

    // Pad to title offset field at byte 84
    rec.resize(84, 0);
    let title_offset = (16 + mobi_header_length as usize + exth.len()) as u32;
    rec.extend_from_slice(&title_offset.to_be_bytes());        // 84-87: title offset
    rec.extend_from_slice(&(title.len() as u32).to_be_bytes()); // 88-91: title length

    // Pad to language at byte 92
    rec.resize(92, 0);
    rec.extend_from_slice(&9u32.to_be_bytes());                // 92-95: language (English)

    // Pad to first image record at byte 108
    rec.resize(108, 0);
    rec.extend_from_slice(&first_image_record.to_be_bytes());  // 108-111: first image

    // Pad to EXTH flags at byte 128
    rec.resize(128, 0);
    rec.extend_from_slice(&0x40u32.to_be_bytes());             // 128-131: EXTH flags

    // Pad to end of MOBI header (16 + 232 = 248)
    rec.resize(16 + mobi_header_length as usize, 0);

    // EXTH records
    rec.extend_from_slice(exth);

    // Title
    rec.extend_from_slice(title.as_bytes());

    // Pad to 4-byte boundary
    while rec.len() % 4 != 0 {
        rec.push(0);
    }

    rec
}

fn build_exth(metadata: &Metadata, cover_offset: Option<u32>) -> Vec<u8> {
    let mut records = Vec::new();
    let mut count = 0u32;

    fn add_record(records: &mut Vec<u8>, rec_type: u32, value: &str, count: &mut u32) {
        let value_bytes = value.as_bytes();
        let rec_len = (8 + value_bytes.len()) as u32;
        records.extend_from_slice(&rec_type.to_be_bytes());
        records.extend_from_slice(&rec_len.to_be_bytes());
        records.extend_from_slice(value_bytes);
        *count += 1;
    }

    fn add_record_u32(records: &mut Vec<u8>, rec_type: u32, value: u32, count: &mut u32) {
        records.extend_from_slice(&rec_type.to_be_bytes());
        records.extend_from_slice(&12u32.to_be_bytes()); // 8 header + 4 value
        records.extend_from_slice(&value.to_be_bytes());
        *count += 1;
    }

    for author in &metadata.authors {
        add_record(&mut records, EXTH_AUTHOR, author, &mut count);
    }
    if let Some(ref p) = metadata.publisher {
        add_record(&mut records, EXTH_PUBLISHER, p, &mut count);
    }
    if let Some(ref d) = metadata.description {
        add_record(&mut records, EXTH_DESCRIPTION, &d[..d.len().min(500)], &mut count);
    }
    if let Some(ref isbn) = metadata.isbn {
        add_record(&mut records, EXTH_ISBN, isbn, &mut count);
    }
    for tag in &metadata.tags {
        add_record(&mut records, EXTH_SUBJECT, tag, &mut count);
    }
    if let Some(ref asin) = metadata.identifiers.get("asin") {
        add_record(&mut records, EXTH_ASIN, asin, &mut count);
    }
    if let Some(offset) = cover_offset {
        add_record_u32(&mut records, EXTH_COVER_OFFSET, offset, &mut count);
        add_record_u32(&mut records, EXTH_THUMB_OFFSET, offset, &mut count);
    }

    // Build EXTH header
    let mut exth = Vec::new();
    exth.extend_from_slice(b"EXTH");
    let header_len = (12 + records.len()) as u32;
    exth.extend_from_slice(&header_len.to_be_bytes());
    exth.extend_from_slice(&count.to_be_bytes());
    exth.extend_from_slice(&records);

    // Pad to 4-byte boundary
    while exth.len() % 4 != 0 {
        exth.push(0);
    }

    exth
}

// ── PalmDOC LZ77 Compression ────────────────────────────────────────────

fn compress_palmdoc(data: &[u8]) -> Vec<Vec<u8>> {
    let record_size = 4096;
    let mut records = Vec::new();

    for chunk in data.chunks(record_size) {
        let mut compressed = Vec::with_capacity(chunk.len());
        let mut i = 0;

        while i < chunk.len() {
            // Simple compression: look for back-references
            let mut best_len = 0;
            let mut best_dist = 0;

            if i >= 1 {
                let max_dist = i.min(2047);
                let max_len = (chunk.len() - i).min(10);

                for dist in 1..=max_dist {
                    let start = i - dist;
                    let mut len = 0;
                    while len < max_len && chunk[start + (len % dist)] == chunk[i + len] {
                        len += 1;
                    }
                    if len >= 3 && len > best_len {
                        best_len = len;
                        best_dist = dist;
                    }
                }
            }

            if best_len >= 3 {
                // Encode as LZ77 back-reference
                let encoded = ((best_dist as u16) << 3) | ((best_len - 3) as u16);
                compressed.push(0x80 | ((encoded >> 8) as u8));
                compressed.push((encoded & 0xFF) as u8);
                i += best_len;
            } else if chunk[i] == b' ' && i + 1 < chunk.len() && chunk[i + 1] >= 0x40 && chunk[i + 1] < 0x80 {
                // Space + printable char
                compressed.push(chunk[i + 1] ^ 0x80);
                i += 2;
            } else if chunk[i] >= 0x09 && chunk[i] <= 0x7F {
                // Literal
                compressed.push(chunk[i]);
                i += 1;
            } else {
                // Literal with count prefix
                compressed.push(1);
                compressed.push(chunk[i]);
                i += 1;
            }
        }

        records.push(compressed);
    }

    records
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn get_record<'a>(data: &'a [u8], palm: &PalmHeader, index: usize) -> Option<&'a [u8]> {
    if index >= palm.record_offsets.len() {
        return None;
    }
    let start = palm.record_offsets[index] as usize;
    let end = if index + 1 < palm.record_offsets.len() {
        palm.record_offsets[index + 1] as usize
    } else {
        data.len()
    };
    if start < data.len() && end <= data.len() {
        Some(&data[start..end])
    } else {
        None
    }
}

/// Normalize Amazon-style "LastName, FirstName" to "FirstName LastName".
/// Leaves names without a comma unchanged.
fn normalize_author(author: &str) -> String {
    let trimmed = author.trim();
    if let Some(comma_pos) = trimmed.find(',') {
        let last = trimmed[..comma_pos].trim();
        let first = trimmed[comma_pos + 1..].trim();
        if !first.is_empty() && !last.is_empty() {
            return format!("{first} {last}");
        }
    }
    trimmed.to_string()
}

fn cp1252_to_char(b: u8) -> char {
    // CP1252 high-byte mapping (128-159 range differs from Latin-1)
    match b {
        0x80 => '\u{20AC}', 0x82 => '\u{201A}', 0x83 => '\u{0192}', 0x84 => '\u{201E}', 0x85 => '\u{2026}',
        0x86 => '\u{2020}', 0x87 => '\u{2021}', 0x88 => '\u{02C6}', 0x89 => '\u{2030}', 0x8A => '\u{0160}',
        0x8B => '\u{2039}', 0x8C => '\u{0152}', 0x8E => '\u{017D}', 0x91 => '\u{2018}', 0x92 => '\u{2019}',
        0x93 => '\u{201C}', 0x94 => '\u{201D}', 0x95 => '\u{2022}', 0x96 => '\u{2013}', 0x97 => '\u{2014}',
        0x98 => '\u{02DC}', 0x99 => '\u{2122}', 0x9A => '\u{0161}', 0x9B => '\u{203A}', 0x9C => '\u{0153}',
        0x9E => '\u{017E}', 0x9F => '\u{0178}',
        _ => char::from(b), // Latin-1 for 160-255
    }
}

fn ensure_xhtml(html: &str) -> String {
    if html.contains("xmlns=\"http://www.w3.org/1999/xhtml\"") {
        return html.to_string();
    }
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<html xmlns=\"http://www.w3.org/1999/xhtml\">\n<head><title>Content</title></head>\n<body>\n{html}\n</body>\n</html>"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mobi_header_alignment() {
        // Verify build_record0 puts fields at the correct absolute offsets
        let exth = build_exth(
            &Metadata::new("Test Title"),
            None,
        );
        let rec0 = build_record0(100, 1, &exth, "Test Title", 0xFFFFFFFF);

        // PalmDOC header
        assert_eq!(
            u16::from_be_bytes([rec0[0], rec0[1]]),
            PALMDOC_COMPRESSION,
            "Bytes 0-1: compression"
        );
        assert_eq!(
            u32::from_be_bytes([rec0[4], rec0[5], rec0[6], rec0[7]]),
            100,
            "Bytes 4-7: text length"
        );
        assert_eq!(
            u16::from_be_bytes([rec0[8], rec0[9]]),
            1,
            "Bytes 8-9: record count"
        );

        // MOBI header
        assert_eq!(&rec0[16..20], b"MOBI", "Bytes 16-19: MOBI magic");
        assert_eq!(
            u32::from_be_bytes([rec0[24], rec0[25], rec0[26], rec0[27]]),
            2,
            "Bytes 24-27: MOBI type (book)"
        );
        assert_eq!(
            u32::from_be_bytes([rec0[28], rec0[29], rec0[30], rec0[31]]),
            65001,
            "Bytes 28-31: encoding (UTF-8)"
        );
        assert_eq!(
            u32::from_be_bytes([rec0[108], rec0[109], rec0[110], rec0[111]]),
            0xFFFFFFFF,
            "Bytes 108-111: first image record"
        );
        assert_eq!(
            u32::from_be_bytes([rec0[128], rec0[129], rec0[130], rec0[131]]),
            0x40,
            "Bytes 128-131: EXTH flags"
        );

        // Title should be readable at the offset stored in bytes 84-87
        let title_off = u32::from_be_bytes([rec0[84], rec0[85], rec0[86], rec0[87]]) as usize;
        let title_len = u32::from_be_bytes([rec0[88], rec0[89], rec0[90], rec0[91]]) as usize;
        assert_eq!(
            &rec0[title_off..title_off + title_len],
            b"Test Title",
            "Title at declared offset"
        );

        // EXTH should be findable
        let exth_pos = rec0.windows(4).position(|w| w == b"EXTH");
        assert!(exth_pos.is_some(), "EXTH magic should be present");
    }

    #[test]
    fn test_mobi_write_read_roundtrip() {
        // Write a MOBI, read it back, verify all fields
        let mut doc = crate::pipeline::document::OebDocument::new();
        doc.metadata = Metadata::new("Roundtrip Test");
        doc.metadata.authors = vec!["Author Née".to_string()];
        doc.metadata.language = Some("fr".to_string());
        doc.add_html("ch1.xhtml",
            "<html xmlns=\"http://www.w3.org/1999/xhtml\"><body><p>Café résumé</p></body></html>");

        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("roundtrip.mobi");
        write(&doc, &path).expect("write");

        let doc2 = read(&path).expect("read");
        assert_eq!(doc2.metadata.title, "Roundtrip Test");
        assert_eq!(doc2.metadata.authors, vec!["Author Née"]);
        let text = doc2.plain_text();
        assert!(text.contains("Café"), "UTF-8 text should survive roundtrip");
        assert!(text.contains("résumé"), "UTF-8 accents should survive roundtrip");
    }

    #[test]
    fn test_palmdoc_roundtrip() {
        let original = b"Hello, this is a test of the PalmDOC compression algorithm. \
                         It should handle repeated patterns like test test test efficiently.";
        let compressed = compress_palmdoc(original);
        assert!(!compressed.is_empty());
        let decompressed = decompress_palmdoc(&compressed[0]);
        assert_eq!(&decompressed[..original.len()], &original[..]);
    }

    #[test]
    fn test_palmdoc_utf8_roundtrip() {
        let original = "Héllo, café résumé — «français» ça été".as_bytes();
        let compressed = compress_palmdoc(original);
        assert!(!compressed.is_empty());
        let decompressed = decompress_palmdoc(&compressed[0]);
        assert_eq!(
            &decompressed[..original.len()],
            original,
            "UTF-8 bytes should survive PalmDOC roundtrip.\n\
             Original: {:?}\n\
             Got:      {:?}",
            String::from_utf8_lossy(original),
            String::from_utf8_lossy(&decompressed[..original.len()])
        );
    }

    #[test]
    fn test_cp1252() {
        assert_eq!(cp1252_to_char(0x93), '\u{201C}'); // left double quote
        assert_eq!(cp1252_to_char(0x94), '\u{201D}'); // right double quote
        assert_eq!(cp1252_to_char(0x80), '\u{20AC}'); // euro sign
    }

    #[test]
    fn test_normalize_author() {
        // Amazon "LastName, FirstName" format
        assert_eq!(normalize_author("Austen, Jane"), "Jane Austen");
        assert_eq!(normalize_author("García Márquez, Gabriel"), "Gabriel García Márquez");
        // Already normal
        assert_eq!(normalize_author("Jane Austen"), "Jane Austen");
        // Edge cases
        assert_eq!(normalize_author("Austen,Jane"), "Jane Austen");
        assert_eq!(normalize_author("  Austen , Jane  "), "Jane Austen");
        // Single name (no comma)
        assert_eq!(normalize_author("Voltaire"), "Voltaire");
    }

    #[test]
    fn test_huff_tables_load() {
        // Build a minimal valid HUFF record:
        // Header: "HUFF" + 0x00000018 (fixed) + off1 (24) + off2 (24 + 1024)
        let mut huff = Vec::new();
        huff.extend_from_slice(b"HUFF");
        huff.extend_from_slice(&0x18u32.to_be_bytes()); // header length
        let off1: u32 = 24; // table1 starts right after 24-byte header
        let off2: u32 = off1 + 256 * 4; // table2 starts after table1
        huff.extend_from_slice(&off1.to_be_bytes());
        huff.extend_from_slice(&off2.to_be_bytes());
        // Pad to off1
        huff.resize(off1 as usize, 0);
        // table1: 256 entries, all terminal with codelen=8
        for i in 0u32..256 {
            let entry = (i << 8) | 0x88; // codelen=8, terminal=0x80
            huff.extend_from_slice(&entry.to_be_bytes());
        }
        // table2: 64 entries (32 pairs of min/max), all zeros
        huff.resize(huff.len() + 64 * 4, 0);

        let tables = HuffTables::load_huff(&huff).expect("valid synthetic HUFF record");
        assert_eq!(tables.table1.len(), 256);
    }

    #[test]
    fn test_cdic_load() {
        // Build a minimal CDIC record with one phrase.
        // Layout: [CDIC header 16 bytes] [offset table] [phrase data]
        // The offset table entries are relative to byte 16.
        // With bits=0, we have 1 entry (2^0 = 1).
        // The offset table is at byte 16, taking 2 bytes.
        // So phrase data starts at byte 18, which is offset 2 from byte 16.
        let mut cdic = Vec::new();
        cdic.extend_from_slice(b"CDIC");
        cdic.extend_from_slice(&0x10u32.to_be_bytes()); // header length = 16
        cdic.extend_from_slice(&1u32.to_be_bytes());    // phrases = 1
        cdic.extend_from_slice(&0u32.to_be_bytes());    // bits = 0 → 1 entry
        // Offset table: 1 x u16. The phrase data is at offset 2 from byte 16.
        cdic.extend_from_slice(&2u16.to_be_bytes());
        // Phrase data at byte 18 (= byte 16 + offset 2):
        // blen: 0x8005 = terminal flag (0x8000) | length 5
        cdic.extend_from_slice(&0x8005u16.to_be_bytes());
        cdic.extend_from_slice(b"Hello");

        // Build minimal HUFF tables first
        let mut huff = Vec::new();
        huff.extend_from_slice(b"HUFF");
        huff.extend_from_slice(&0x18u32.to_be_bytes());
        let off1: u32 = 24;
        let off2: u32 = off1 + 256 * 4;
        huff.extend_from_slice(&off1.to_be_bytes());
        huff.extend_from_slice(&off2.to_be_bytes());
        huff.resize(off1 as usize, 0);
        for i in 0u32..256 {
            let entry = (i << 8) | 0x88;
            huff.extend_from_slice(&entry.to_be_bytes());
        }
        huff.resize(huff.len() + 64 * 4, 0);

        let mut tables = HuffTables::load_huff(&huff).expect("valid synthetic HUFF record");
        assert!(tables.load_cdic(&cdic).is_ok());
        assert_eq!(tables.dictionary.len(), 1);
        assert_eq!(tables.dictionary[0].0, b"Hello");
        assert!(tables.dictionary[0].1); // terminal
    }
}
