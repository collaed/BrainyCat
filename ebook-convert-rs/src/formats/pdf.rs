//! PDF reader and writer.
//!
//! Reading: Extract text, images, and structure from PDF using lopdf.
//! Writing: Generate PDF from OEB document using printpdf.
//!
//! PDF reading is inherently lossy — PDFs contain positioned glyphs, not
//! semantic text. We use heuristics for paragraph detection and reading order.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

use crate::pipeline::document::{OebDocument, TocEntry};
use crate::pipeline::metadata::Metadata;

static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
static RE_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<h([1-3])[^>]*>(.*?)</h[1-3]>").unwrap());
static RE_PARA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<p[^>]*>(.*?)</p>").unwrap());
static RE_CHAPTER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?im)^(?:chapter|part|section)\s+[\divxlc]+[.:\s]*(.*)").unwrap());

// ── Reader ──────────────────────────────────────────────────────────────

/// Read a PDF file into an OEB document.
///
/// Extracts text page by page, detects headings by font size,
/// and extracts embedded images.
pub fn read(path: &Path) -> Result<OebDocument> {
    let pdf_bytes = std::fs::read(path)?;
    let pdf = match lopdf::Document::load_mem(&pdf_bytes) {
        Ok(p) => p,
        Err(e) if crate::pipeline::is_lenient() => {
            tracing::warn!("PDF parse failed, returning empty document: {e}");
            let mut doc = OebDocument::new();
            doc.metadata = Metadata::new(
                path.file_stem().and_then(|s| s.to_str()).unwrap_or("Untitled"),
            );
            return Ok(doc);
        }
        Err(e) => return Err(e).context("Failed to parse PDF"),
    };

    let mut doc = OebDocument::new();

    // Extract metadata from PDF info dictionary
    doc.metadata = extract_pdf_metadata(&pdf, path);

    // Extract text page by page
    let pages = pdf.get_pages();
    let mut all_text = Vec::new();
    let mut page_texts = Vec::new();

    for (&page_num, &_page_id) in &pages {
        let text = pdf.extract_text(&[page_num]).unwrap_or_default();
        if !text.trim().is_empty() {
            page_texts.push((page_num, text.clone()));
            all_text.push(text);
        }
    }

    if page_texts.is_empty() {
        tracing::warn!("PDF has {} pages but no extractable text (scanned/image-only?)", pages.len());
    }

    // Detect chapters from text patterns
    let chapters = detect_chapters_from_text(&all_text.join("\n\n"));

    if chapters.len() > 1 {
        // Split into chapter files
        for (i, (title, content)) in chapters.iter().enumerate() {
            let xhtml = text_to_xhtml(content, title);
            let name = format!("ch_{:03}.xhtml", i);
            doc.add_html(&name, xhtml);
            doc.toc.push(TocEntry {
                title: title.clone(),
                href: name,
                children: Vec::new(),
            });
        }
    } else {
        // Single file — split by pages, grouping ~10 pages per file
        let pages_per_file = 10;
        for (chunk_idx, chunk) in page_texts.chunks(pages_per_file).enumerate() {
            let combined: String = chunk.iter().map(|(_, t)| t.as_str()).collect::<Vec<_>>().join("\n\n");
            let title = format!("Pages {}-{}", chunk[0].0, chunk.last().map(|(n, _)| *n).unwrap_or(0));
            let xhtml = text_to_xhtml(&combined, &title);
            let name = format!("pages_{:03}.xhtml", chunk_idx);
            doc.add_html(&name, xhtml);
        }
    }

    // Extract images — walk all objects (more reliable than per-page)
    let extracted_images = extract_all_images(&pdf);
    for (name, data) in &extracted_images {
        let (_, mime) = detect_image_format(data);
        doc.add_image(name, data.clone(), mime);
    }

    tracing::info!(
        "Read PDF: {} pages, {} chapters, {} images",
        pages.len(),
        doc.toc.len(),
        extracted_images.len()
    );

    Ok(doc)
}

// ── Writer ──────────────────────────────────────────────────────────────

/// Write an OEB document as a PDF file.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    use printpdf::*;

    let title = &doc.metadata.title;
    let mut pdf_doc = PdfDocument::new(title);

    let page_width_mm = Mm(210.0);  // A4
    let page_height_mm = Mm(297.0);
    let margin = Pt(72.0);          // 1 inch
    let page_width_pt = Pt(595.0);
    let page_height_pt = Pt(842.0);
    let text_width = page_width_pt.0 - margin.0 * 2.0;

    // Try to load an external font from the document's font map, fall back to builtin
    let (use_external, ext_font_id, parsed_font_opt) = load_document_font(&mut pdf_doc, doc);

    let font_size_body = 11.0_f32;
    let font_size_h1 = 22.0_f32;
    let font_size_h2 = 16.0_f32;
    let line_height = Pt(font_size_body * 1.4);

    let strip_tags = &*RE_STRIP_TAGS;
    let heading_re = &*RE_HEADING;
    let para_re = &*RE_PARA;

    let mut ops: Vec<Op> = Vec::new();
    let mut y_pos = page_height_pt.0 - margin.0;
    let mut pages: Vec<PdfPage> = Vec::new();

    // Helper: estimate text width using glyph metrics or char-count fallback
    let avg_char_width = if let Some(ref pf) = parsed_font_opt {
        // Use space width as a baseline, scaled to font size
        let units_per_em = pf.font_metrics.units_per_em as f32;
        let space_w = pf.get_space_width().unwrap_or(250) as f32;
        (space_w / units_per_em) * font_size_body
    } else {
        // Helvetica approximate: ~0.5 * font_size for average char
        font_size_body * 0.5
    };
    let chars_per_line = (text_width / avg_char_width).floor() as usize;

    /// Flush current ops into a page and start a new one.
    fn new_page(
        pages: &mut Vec<PdfPage>,
        ops: &mut Vec<Op>,
        y_pos: &mut f32,
        page_width: Mm,
        page_height: Mm,
        margin: Pt,
    ) {
        if !ops.is_empty() {
            pages.push(PdfPage::new(page_width, page_height, std::mem::take(ops)));
        }
        *y_pos = page_height.into_pt().0 - margin.0;
    }

    for name in &doc.spine {
        let html = match doc.html_files.get(name) {
            Some(h) => h,
            None => continue,
        };

        // Process headings
        for cap in heading_re.captures_iter(html) {
            let level: u8 = cap[1].parse().unwrap_or(1);
            let text = strip_tags.replace_all(&cap[2], "").trim().to_string();
            if text.is_empty() {
                continue;
            }

            // New page for h1
            if level == 1 && y_pos < page_height_pt.0 - margin.0 - 10.0 {
                new_page(&mut pages, &mut ops, &mut y_pos, page_width_mm, page_height_mm, margin);
            }

            let size = match level {
                1 => font_size_h1,
                2 => font_size_h2,
                _ => 13.0,
            };

            y_pos -= size * 0.8;
            if y_pos < margin.0 + 10.0 {
                new_page(&mut pages, &mut ops, &mut y_pos, page_width_mm, page_height_mm, margin);
            }

            ops.push(Op::StartTextSection);
            ops.push(Op::SetTextCursor { pos: Point { x: margin, y: Pt(y_pos) } });
            if use_external {
                ops.push(Op::SetFontSize { size: Pt(size), font: ext_font_id.clone() });
                ops.push(Op::WriteText {
                    items: vec![TextItem::Text(text)],
                    font: ext_font_id.clone(),
                });
            } else {
                ops.push(Op::SetFontSizeBuiltinFont { size: Pt(size), font: BuiltinFont::HelveticaBold });
                ops.push(Op::WriteTextBuiltinFont {
                    items: vec![TextItem::Text(text)],
                    font: BuiltinFont::HelveticaBold,
                });
            }
            ops.push(Op::EndTextSection);
            y_pos -= line_height.0;
        }

        // Process paragraphs
        for cap in para_re.captures_iter(html) {
            let text = strip_tags.replace_all(&cap[1], "").trim().to_string();
            if text.is_empty() {
                continue;
            }

            let words: Vec<&str> = text.split_whitespace().collect();
            let mut line = String::new();

            for word in words {
                if line.len() + word.len() + 1 > chars_per_line && !line.is_empty() {
                    if y_pos < margin.0 + 10.0 {
                        new_page(&mut pages, &mut ops, &mut y_pos, page_width_mm, page_height_mm, margin);
                    }
                    ops.push(Op::StartTextSection);
                    ops.push(Op::SetTextCursor { pos: Point { x: margin, y: Pt(y_pos) } });
                    if use_external {
                        ops.push(Op::SetFontSize { size: Pt(font_size_body), font: ext_font_id.clone() });
                        ops.push(Op::WriteText {
                            items: vec![TextItem::Text(line.clone())],
                            font: ext_font_id.clone(),
                        });
                    } else {
                        ops.push(Op::SetFontSizeBuiltinFont { size: Pt(font_size_body), font: BuiltinFont::Helvetica });
                        ops.push(Op::WriteTextBuiltinFont {
                            items: vec![TextItem::Text(line.clone())],
                            font: BuiltinFont::Helvetica,
                        });
                    }
                    ops.push(Op::EndTextSection);
                    y_pos -= line_height.0;
                    line = word.to_string();
                } else {
                    if !line.is_empty() {
                        line.push(' ');
                    }
                    line.push_str(word);
                }
            }

            if !line.is_empty() {
                if y_pos < margin.0 + 10.0 {
                    new_page(&mut pages, &mut ops, &mut y_pos, page_width_mm, page_height_mm, margin);
                }
                ops.push(Op::StartTextSection);
                ops.push(Op::SetTextCursor { pos: Point { x: margin, y: Pt(y_pos) } });
                if use_external {
                    ops.push(Op::SetFontSize { size: Pt(font_size_body), font: ext_font_id.clone() });
                    ops.push(Op::WriteText {
                        items: vec![TextItem::Text(line)],
                        font: ext_font_id.clone(),
                    });
                } else {
                    ops.push(Op::SetFontSizeBuiltinFont { size: Pt(font_size_body), font: BuiltinFont::Helvetica });
                    ops.push(Op::WriteTextBuiltinFont {
                        items: vec![TextItem::Text(line)],
                        font: BuiltinFont::Helvetica,
                    });
                }
                ops.push(Op::EndTextSection);
                y_pos -= line_height.0;
            }

            y_pos -= Pt(3.0).0; // paragraph spacing
        }
    }

    // Flush remaining ops as the last page
    if !ops.is_empty() {
        pages.push(PdfPage::new(page_width_mm, page_height_mm, ops));
    }

    // Ensure at least one page
    if pages.is_empty() {
        pages.push(PdfPage::new(page_width_mm, page_height_mm, vec![]));
    }

    pdf_doc.with_pages(pages);

    let mut warnings = Vec::new();
    let bytes = pdf_doc.save(&PdfSaveOptions::default(), &mut warnings);
    std::fs::write(path, bytes)?;

    for w in &warnings {
        tracing::warn!("PDF save warning: {:?}", w);
    }
    tracing::info!("Wrote PDF: {}", path.display());
    Ok(())
}

/// Try to load an external TTF/OTF font from the document's font map.
/// Returns (is_external, font_id, parsed_font) — if no external font is
/// available, font_id is a dummy and the caller should use BuiltinFont.
fn load_document_font(
    pdf_doc: &mut printpdf::PdfDocument,
    doc: &OebDocument,
) -> (bool, printpdf::FontId, Option<printpdf::ParsedFont>) {
    // Look for a TTF or OTF font in the document
    for (name, data) in &doc.fonts {
        let is_font = name.ends_with(".ttf")
            || name.ends_with(".otf")
            || name.ends_with(".TTF")
            || name.ends_with(".OTF");
        if !is_font || data.is_empty() {
            continue;
        }

        let mut warnings = Vec::new();
        if let Some(parsed) = printpdf::ParsedFont::from_bytes(data, 0, &mut warnings) {
            let font_id = pdf_doc.add_font(&parsed);
            tracing::info!("Embedded font: {name}");
            return (true, font_id, Some(parsed));
        }
    }

    // No external font available — return dummy FontId; caller uses BuiltinFont
    (false, printpdf::FontId::new(), None)
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn extract_pdf_metadata(pdf: &lopdf::Document, path: &Path) -> Metadata {
    let mut m = Metadata::new(
        path.file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("Untitled"),
    );

    // Try to read from PDF info dictionary
    if let Ok(info) = pdf.trailer.get(b"Info") {
        if let Ok(info_ref) = info.as_reference() {
            if let Ok(info_obj) = pdf.get_object(info_ref) {
                if let Ok(dict) = info_obj.as_dict() {
                    if let Ok(title) = dict.get(b"Title").and_then(|v| v.as_str()) {
                        let t = String::from_utf8_lossy(title).to_string();
                        if !t.is_empty() {
                            m.title = t;
                        }
                    }
                    if let Ok(author) = dict.get(b"Author").and_then(|v| v.as_str()) {
                        let a = String::from_utf8_lossy(author).to_string();
                        if !a.is_empty() {
                            m.authors = vec![a];
                        }
                    }
                    if let Ok(subject) = dict.get(b"Subject").and_then(|v| v.as_str()) {
                        let s = String::from_utf8_lossy(subject).to_string();
                        if !s.is_empty() {
                            m.description = Some(s);
                        }
                    }
                }
            }
        }
    }

    m
}

fn detect_chapters_from_text(text: &str) -> Vec<(String, String)> {
    let chapter_re = &*RE_CHAPTER;

    let matches: Vec<_> = chapter_re.find_iter(text).collect();
    if matches.is_empty() {
        return vec![("Content".into(), text.into())];
    }

    let mut chapters = Vec::new();
    for (i, m) in matches.iter().enumerate() {
        let title = chapter_re.captures(m.as_str())
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_else(|| format!("Chapter {}", i + 1));

        let start = m.start();
        let end = if i + 1 < matches.len() {
            matches[i + 1].start()
        } else {
            text.len()
        };

        chapters.push((title, text[start..end].to_string()));
    }

    chapters
}

fn text_to_xhtml(text: &str, title: &str) -> String {
    let paragraphs: String = text
        .split("\n\n")
        .filter(|p| !p.trim().is_empty())
        .map(|p| {
            let escaped = p.trim()
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            format!("<p>{escaped}</p>")
        })
        .collect::<Vec<_>>()
        .join("\n");

    let escaped_title = title.replace('&', "&amp;").replace('<', "&lt;");
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{escaped_title}</title></head>
<body>
<h1>{escaped_title}</h1>
{paragraphs}
</body>
</html>"#
    )
}

fn get_page_resources(pdf: &lopdf::Document, page_id: lopdf::ObjectId) -> Result<HashMap<String, lopdf::ObjectId>> {
    let mut images = HashMap::new();
    let page = pdf.get_object(page_id)
        .and_then(|o| o.as_dict().map(|d| d.clone()))
        .unwrap_or_default();

    // Get Resources dict (may be direct or indirect reference)
    let resources = if let Ok(res_ref) = page.get(b"Resources") {
        match res_ref {
            lopdf::Object::Reference(id) => pdf.get_object(*id)
                .and_then(|o| o.as_dict().map(|d| d.clone()))
                .unwrap_or_default(),
            lopdf::Object::Dictionary(d) => d.clone(),
            _ => return Ok(images),
        }
    } else {
        return Ok(images);
    };

    // Get XObject subdictionary (where images live)
    let xobjects = if let Ok(xobj_ref) = resources.get(b"XObject") {
        match xobj_ref {
            lopdf::Object::Reference(id) => pdf.get_object(*id)
                .and_then(|o| o.as_dict().map(|d| d.clone()))
                .unwrap_or_default(),
            lopdf::Object::Dictionary(d) => d.clone(),
            _ => return Ok(images),
        }
    } else {
        return Ok(images);
    };

    for (name, obj) in xobjects.iter() {
        if let lopdf::Object::Reference(id) = obj {
            images.insert(String::from_utf8_lossy(name).to_string(), *id);
        }
    }

    Ok(images)
}

/// Alternate image extraction: walk all objects looking for image streams.
fn extract_all_images(pdf: &lopdf::Document) -> Vec<(String, Vec<u8>)> {
    let mut images = Vec::new();
    let mut count = 0;

    for (_id, object) in pdf.objects.iter() {
        if let Ok(stream) = object.as_stream() {
            let subtype = stream.dict.get(b"Subtype")
                .ok()
                .and_then(|v| v.as_name().ok())
                .map(|n| String::from_utf8_lossy(n).to_string());

            if subtype.as_deref() == Some("Image") {
                let mut data = stream.content.clone();

                let filter = stream.dict.get(b"Filter")
                    .ok()
                    .and_then(|v| v.as_name().ok())
                    .map(|n| String::from_utf8_lossy(n).to_string());

                let (ext, _mime) = match filter.as_deref() {
                    Some("DCTDecode") => ("jpg", "image/jpeg"),
                    Some("JPXDecode") => ("jp2", "image/jp2"),
                    Some("FlateDecode") => {
                        if let Ok(decoded) = stream.decompressed_content() {
                            data = decoded;
                        }
                        ("png", "image/png")
                    }
                    _ => detect_image_format(&data),
                };

                if !data.is_empty() && data.len() > 8 {
                    let name = format!("image_{count:03}.{ext}");
                    images.push((name, data));
                    count += 1;
                }
            }
        }
    }

    images
}

fn detect_image_format(data: &[u8]) -> (&str, &str) {
    if data.starts_with(&[0xFF, 0xD8, 0xFF]) {
        ("jpg", "image/jpeg")
    } else if data.starts_with(b"\x89PNG") {
        ("png", "image/png")
    } else {
        ("bin", "application/octet-stream")
    }
}
