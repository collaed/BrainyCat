//! EPUB reader and writer.
//!
//! EPUB is a ZIP containing:
//!   META-INF/container.xml → points to content.opf
//!   content.opf → manifest + spine + metadata
//!   *.xhtml → content files
//!   *.css → stylesheets
//!   images/* → images
//!
//! This handles EPUB 2 and EPUB 3.

use anyhow::{Context, Result};
use quick_xml::events::Event;
use quick_xml::Reader;
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;
use std::sync::LazyLock;
use zip::ZipArchive;

use regex::Regex;

use crate::pipeline::document::{GuideRef, OebDocument, TocEntry};

static RE_NAV_TOC: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"(?s)<nav[^>]*epub:type="toc"[^>]*>(.*?)</nav>"#).unwrap());
static RE_NAV_LINK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>"#).unwrap());
static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
use crate::pipeline::metadata::Metadata;

// ── Reader ──────────────────────────────────────────────────────────────

/// Read an EPUB file into an OEB document.
pub fn read(path: &Path) -> Result<OebDocument> {
    let file = std::fs::File::open(path)?;
    let mut archive = ZipArchive::new(file)?;
    let mut doc = OebDocument::new();

    // 1. Find OPF path from container.xml
    let opf_path = find_opf_path(&mut archive)?;
    let opf_dir = opf_path
        .rfind('/')
        .map(|i| &opf_path[..i + 1])
        .unwrap_or("");

    // 2. Parse OPF
    let opf_content = read_zip_text(&mut archive, &opf_path)?;
    let opf_result = parse_opf(&opf_content, opf_dir);
    let (metadata, manifest, spine, guide) = match opf_result {
        Ok(parsed) => parsed,
        Err(e) if crate::pipeline::is_lenient() => {
            tracing::warn!("OPF parse failed, continuing with empty metadata: {e}");
            (
                crate::pipeline::metadata::Metadata::new("Unknown"),
                HashMap::new(),
                Vec::new(),
                Vec::new(),
            )
        }
        Err(e) => return Err(e),
    };
    doc.metadata = metadata;
    doc.guide = guide;

    // 3. Load all manifest items
    for (id, (href, media_type)) in &manifest {
        let full_path = if href.starts_with('/') {
            href[1..].to_string()
        } else {
            format!("{opf_dir}{href}")
        };

        match media_type.as_str() {
            "application/xhtml+xml" | "text/html" => {
                if let Ok(content) = read_zip_text(&mut archive, &full_path) {
                    doc.html_files.insert(href.clone(), content);
                    doc.mime_map
                        .insert(href.clone(), media_type.clone());
                }
            }
            "text/css" => {
                if let Ok(content) = read_zip_text(&mut archive, &full_path) {
                    doc.stylesheets.insert(href.clone(), content);
                    doc.mime_map
                        .insert(href.clone(), media_type.clone());
                }
            }
            mt if mt.starts_with("image/") => {
                if let Ok(data) = read_zip_bytes(&mut archive, &full_path) {
                    doc.images.insert(href.clone(), data);
                    doc.mime_map
                        .insert(href.clone(), media_type.clone());
                }
            }
            mt if mt.starts_with("font/") || mt == "application/font-woff" || mt.contains("opentype") => {
                if let Ok(data) = read_zip_bytes(&mut archive, &full_path) {
                    doc.fonts.insert(href.clone(), data);
                    doc.mime_map
                        .insert(href.clone(), media_type.clone());
                }
            }
            _ => {
                tracing::debug!("Skipping manifest item: {href} ({media_type})");
            }
        }
    }

    // 4. Build spine from OPF spine references
    let id_to_href: HashMap<&str, &str> = manifest
        .iter()
        .map(|(id, (href, _))| (id.as_str(), href.as_str()))
        .collect();
    for idref in &spine {
        if let Some(href) = id_to_href.get(idref.as_str()) {
            doc.spine.push(href.to_string());
        }
    }

    // 5. Parse TOC (NCX for EPUB2, nav for EPUB3)
    doc.toc = parse_toc(&mut archive, &manifest, opf_dir)?;

    tracing::info!(
        "Read EPUB: {} files, {} images, {} in spine",
        doc.html_files.len(),
        doc.images.len(),
        doc.spine.len()
    );

    Ok(doc)
}

// ── Writer ──────────────────────────────────────────────────────────────

/// Write an OEB document as an EPUB 3 file.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::CompressionMethod;

    let file = std::fs::File::create(path)?;
    let mut zip = zip::ZipWriter::new(file);
    let stored = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
    let deflated = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

    // 1. mimetype (must be first, uncompressed, no extra field)
    zip.start_file("mimetype", stored)?;
    zip.write_all(b"application/epub+zip")?;

    // 2. META-INF/container.xml
    zip.start_file("META-INF/container.xml", deflated)?;
    zip.write_all(
        br#"<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"#,
    )?;

    // 3. Generate OPF
    let opf = generate_opf(doc);
    zip.start_file("OEBPS/content.opf", deflated)?;
    zip.write_all(opf.as_bytes())?;

    // 4. Generate navigation document (EPUB 3 nav)
    let nav = generate_nav(doc);
    zip.start_file("OEBPS/nav.xhtml", deflated)?;
    zip.write_all(nav.as_bytes())?;

    // 5. Write content files
    for (name, content) in &doc.html_files {
        zip.start_file(format!("OEBPS/{name}"), deflated)?;
        zip.write_all(content.as_bytes())?;
    }

    // 6. Write stylesheets
    for (name, content) in &doc.stylesheets {
        zip.start_file(format!("OEBPS/{name}"), deflated)?;
        zip.write_all(content.as_bytes())?;
    }

    // 7. Write images
    for (name, data) in &doc.images {
        zip.start_file(format!("OEBPS/{name}"), deflated)?;
        zip.write_all(data)?;
    }

    // 8. Write fonts
    for (name, data) in &doc.fonts {
        zip.start_file(format!("OEBPS/{name}"), deflated)?;
        zip.write_all(data)?;
    }

    zip.finish()?;
    tracing::info!("Wrote EPUB: {}", path.display());
    Ok(())
}

// ── OPF Generation ──────────────────────────────────────────────────────

fn generate_opf(doc: &OebDocument) -> String {
    let m = &doc.metadata;
    let uuid = m.uuid.as_deref().unwrap_or("urn:uuid:00000000-0000-0000-0000-000000000000");
    let lang = m.primary_language();
    let title = xml_escape(&m.title);
    let authors: String = m.authors.iter()
        .map(|a| format!("    <dc:creator>{}</dc:creator>", xml_escape(a)))
        .collect::<Vec<_>>().join("\n");
    let desc = m.description.as_ref()
        .map(|d| format!("    <dc:description>{}</dc:description>", xml_escape(d)))
        .unwrap_or_default();
    let publisher = m.publisher.as_ref()
        .map(|p| format!("    <dc:publisher>{}</dc:publisher>", xml_escape(p)))
        .unwrap_or_default();

    // Manifest items
    let mut manifest_items = String::new();
    manifest_items.push_str("    <item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>\n");

    for (i, name) in doc.spine.iter().enumerate() {
        let mime = doc.mime_map.get(name).map(|s| s.as_str()).unwrap_or("application/xhtml+xml");
        manifest_items.push_str(&format!(
            "    <item id=\"content_{i}\" href=\"{name}\" media-type=\"{mime}\"/>\n"
        ));
    }
    for (name, mime) in &doc.mime_map {
        if !doc.spine.contains(name) && name != "nav.xhtml" {
            let id = name.replace(['/', '.', '-'], "_");
            manifest_items.push_str(&format!(
                "    <item id=\"{id}\" href=\"{name}\" media-type=\"{mime}\"/>\n"
            ));
        }
    }

    // Spine
    let spine_items: String = (0..doc.spine.len())
        .map(|i| format!("    <itemref idref=\"content_{i}\"/>"))
        .collect::<Vec<_>>().join("\n");

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">{uuid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>{lang}</dc:language>
{authors}
{desc}
{publisher}
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
{manifest_items}  </manifest>
  <spine>
{spine_items}
  </spine>
</package>"#,
        modified = chrono_now(),
    )
}

fn generate_nav(doc: &OebDocument) -> String {
    let mut entries = String::new();
    for entry in &doc.toc {
        entries.push_str(&format!(
            "      <li><a href=\"{}\">{}</a></li>\n",
            entry.href,
            xml_escape(&entry.title)
        ));
    }
    if entries.is_empty() && !doc.spine.is_empty() {
        entries = format!(
            "      <li><a href=\"{}\">{}</a></li>\n",
            doc.spine[0],
            xml_escape(&doc.metadata.title)
        );
    }

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Table of Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{entries}    </ol>
  </nav>
</body>
</html>"#
    )
}

// ── OPF Parsing ─────────────────────────────────────────────────────────

fn find_opf_path(archive: &mut ZipArchive<std::fs::File>) -> Result<String> {
    let container = read_zip_text(archive, "META-INF/container.xml")?;
    let mut reader = Reader::from_str(&container);
    loop {
        match reader.read_event() {
            Ok(Event::Empty(ref e)) | Ok(Event::Start(ref e)) if e.name().as_ref() == b"rootfile" => {
                for attr in e.attributes().flatten() {
                    if attr.key.as_ref() == b"full-path" {
                        return Ok(String::from_utf8_lossy(&attr.value).into_owned());
                    }
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(e.into()),
            _ => {}
        }
    }
    anyhow::bail!("No rootfile found in container.xml")
}

/// Parse OPF → (metadata, manifest{id→(href,media-type)}, spine[idref], guide)
fn parse_opf(
    opf: &str,
    _opf_dir: &str,
) -> Result<(
    Metadata,
    HashMap<String, (String, String)>,
    Vec<String>,
    Vec<GuideRef>,
)> {
    let mut metadata = Metadata::default();
    let mut manifest: HashMap<String, (String, String)> = HashMap::new();
    let mut spine: Vec<String> = Vec::new();
    let mut guide: Vec<GuideRef> = Vec::new();

    let mut reader = Reader::from_str(opf);
    let mut buf_text = String::new();
    let mut in_metadata = false;
    let mut current_tag = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);

                match local {
                    "metadata" => in_metadata = true,
                    "title" | "creator" | "publisher" | "description" | "language"
                    | "identifier" | "date" | "subject" if in_metadata => {
                        current_tag = local.to_string();
                        buf_text.clear();
                    }
                    _ => {}
                }
            }
            Ok(Event::Empty(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);
                let attrs = extract_attrs(e);

                match local {
                    "item" => {
                        if let (Some(id), Some(href), Some(mt)) =
                            (attrs.get("id"), attrs.get("href"), attrs.get("media-type"))
                        {
                            manifest.insert(id.clone(), (href.clone(), mt.clone()));
                        }
                    }
                    "itemref" => {
                        if let Some(idref) = attrs.get("idref") {
                            spine.push(idref.clone());
                        }
                    }
                    "reference" => {
                        if let (Some(t), Some(href)) = (attrs.get("type"), attrs.get("href")) {
                            guide.push(GuideRef {
                                ref_type: t.clone(),
                                title: attrs.get("title").cloned().unwrap_or_default(),
                                href: href.clone(),
                            });
                        }
                    }
                    _ => {}
                }
            }
            Ok(Event::Text(ref e)) => {
                if in_metadata && !current_tag.is_empty() {
                    buf_text.push_str(&e.unescape().unwrap_or_default());
                }
            }
            Ok(Event::End(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);

                if local == "metadata" {
                    in_metadata = false;
                }
                if in_metadata && !buf_text.is_empty() {
                    let val = buf_text.trim().to_string();
                    match current_tag.as_str() {
                        "title" => metadata.title = val,
                        "creator" => metadata.authors.push(val),
                        "publisher" => metadata.publisher = Some(val),
                        "description" => metadata.description = Some(val),
                        "language" => {
                            metadata.language = Some(val.clone());
                            metadata.languages.push(val);
                        }
                        "identifier" => {
                            if val.starts_with("978") || val.starts_with("979") {
                                metadata.isbn = Some(val.clone());
                            }
                            metadata.identifiers.insert("opf".into(), val);
                        }
                        "date" => metadata.pubdate = Some(val),
                        "subject" => metadata.tags.push(val),
                        _ => {}
                    }
                    buf_text.clear();
                    current_tag.clear();
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(e.into()),
            _ => {}
        }
    }

    Ok((metadata, manifest, spine, guide))
}

fn parse_toc(
    archive: &mut ZipArchive<std::fs::File>,
    manifest: &HashMap<String, (String, String)>,
    opf_dir: &str,
) -> Result<Vec<TocEntry>> {
    // Try NCX first (EPUB 2)
    for (_, (href, mt)) in manifest {
        if mt == "application/x-dtbncx+xml" {
            let path = format!("{opf_dir}{href}");
            if let Ok(ncx) = read_zip_text(archive, &path) {
                return parse_ncx(&ncx);
            }
        }
    }
    // Try nav document (EPUB 3)
    for (_, (href, mt)) in manifest {
        if mt == "application/xhtml+xml" && href.contains("nav") {
            let path = format!("{opf_dir}{href}");
            if let Ok(nav_html) = read_zip_text(archive, &path) {
                let entries = parse_epub3_nav(&nav_html);
                if !entries.is_empty() {
                    return Ok(entries);
                }
            }
        }
    }
    Ok(Vec::new())
}

/// Parse EPUB3 navigation document (nav element with epub:type="toc").
fn parse_epub3_nav(html: &str) -> Vec<TocEntry> {
    let mut entries = Vec::new();
    // Find the <nav epub:type="toc"> section
    let toc_re = &*RE_NAV_TOC;
    let link_re = &*RE_NAV_LINK;
    let strip_tags = &*RE_STRIP_TAGS;

    if let Some(toc_match) = toc_re.captures(html) {
        let toc_content = &toc_match[1];
        for cap in link_re.captures_iter(toc_content) {
            let href = cap[1].to_string();
            let title = strip_tags.replace_all(&cap[2], "").trim().to_string();
            if !title.is_empty() {
                entries.push(TocEntry {
                    title,
                    href,
                    children: Vec::new(),
                });
            }
        }
    }
    entries
}

fn parse_ncx(ncx: &str) -> Result<Vec<TocEntry>> {
    let mut entries = Vec::new();
    let mut reader = Reader::from_str(ncx);
    let mut in_navpoint = false;
    let mut in_text = false;
    let mut current_title = String::new();
    let mut current_href = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) => {
                let qname = e.name();
                let name = String::from_utf8_lossy(qname.as_ref());
                match name.as_ref() {
                    "navPoint" => in_navpoint = true,
                    "text" if in_navpoint => in_text = true,
                    _ => {}
                }
            }
            Ok(Event::Empty(ref e)) => {
                let qname = e.name();
                let name = String::from_utf8_lossy(qname.as_ref());
                if name == "content" && in_navpoint {
                    let attrs = extract_attrs(e);
                    if let Some(src) = attrs.get("src") {
                        current_href = src.clone();
                    }
                }
            }
            Ok(Event::Text(ref e)) if in_text => {
                current_title.push_str(&e.unescape().unwrap_or_default());
            }
            Ok(Event::End(ref e)) => {
                let qname = e.name();
                let name = String::from_utf8_lossy(qname.as_ref());
                match name.as_ref() {
                    "text" => in_text = false,
                    "navPoint" => {
                        if !current_title.is_empty() {
                            entries.push(TocEntry {
                                title: current_title.trim().to_string(),
                                href: current_href.clone(),
                                children: Vec::new(),
                            });
                        }
                        current_title.clear();
                        current_href.clear();
                        in_navpoint = false;
                    }
                    _ => {}
                }
            }
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
    }
    Ok(entries)
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn read_zip_text(archive: &mut ZipArchive<std::fs::File>, name: &str) -> Result<String> {
    let mut file = archive.by_name(name).with_context(|| format!("File not in ZIP: {name}"))?;
    // LP#1188843: Some EPUBs claim UTF-8 but contain invalid bytes.
    // Try strict UTF-8 first, fall back to lossy decoding.
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    match String::from_utf8(bytes) {
        Ok(s) => Ok(s),
        Err(e) => {
            tracing::warn!("Invalid UTF-8 in {name}, using lossy decoding");
            Ok(String::from_utf8_lossy(e.as_bytes()).into_owned())
        }
    }
}

fn read_zip_bytes(archive: &mut ZipArchive<std::fs::File>, name: &str) -> Result<Vec<u8>> {
    let mut file = archive.by_name(name).with_context(|| format!("File not in ZIP: {name}"))?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    Ok(data)
}

fn extract_attrs(e: &quick_xml::events::BytesStart) -> HashMap<String, String> {
    e.attributes()
        .flatten()
        .map(|a| {
            (
                String::from_utf8_lossy(a.key.as_ref()).to_string(),
                String::from_utf8_lossy(&a.value).to_string(),
            )
        })
        .collect()
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let days = secs / 86400;
    let years = 1970 + days / 365;
    let rem_days = days % 365;
    let month = rem_days / 30 + 1;
    let day = rem_days % 30 + 1;
    let hour = (secs % 86400) / 3600;
    let min = (secs % 3600) / 60;
    let sec = secs % 60;
    format!("{years:04}-{month:02}-{day:02}T{hour:02}:{min:02}:{sec:02}Z")
}
