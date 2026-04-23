//! DOCX reader and writer.
//!
//! DOCX is a ZIP containing XML files:
//!   [Content_Types].xml → content type mappings
//!   word/document.xml → main content (paragraphs, headings, tables)
//!   word/styles.xml → style definitions
//!   word/media/* → embedded images
//!   word/_rels/document.xml.rels → relationships (images, hyperlinks)
//!
//! We parse the WordprocessingML XML to extract structured content.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
static RE_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<h([1-6])[^>]*>(.*?)</h[1-6]>").unwrap());
static RE_PARA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<p[^>]*>(.*?)</p>").unwrap());
static RE_BOLD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<(?:strong|b)>(.*?)</(?:strong|b)>").unwrap());
static RE_ITALIC: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<(?:em|i)>(.*?)</(?:em|i)>").unwrap());
static RE_DC_TITLE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<dc:title>(.*?)</dc:title>").unwrap());
static RE_DC_CREATOR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<dc:creator>(.*?)</dc:creator>").unwrap());
static RE_DC_DESC: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<dc:description>(.*?)</dc:description>").unwrap());
static RE_DC_LANG: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<dc:language>(.*?)</dc:language>").unwrap());
static RE_REL_ID: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"Id="([^"]+)"[^>]*Target="([^"]+)""#).unwrap());
use zip::ZipArchive;

use crate::pipeline::document::{OebDocument, TocEntry};
use crate::pipeline::metadata::Metadata;

const W_NS: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const R_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const A_NS: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";

// ── Reader ──────────────────────────────────────────────────────────────

/// Read a DOCX file into an OEB document.
pub fn read(path: &Path) -> Result<OebDocument> {
    let file = std::fs::File::open(path)?;
    let mut archive = ZipArchive::new(file)?;
    let mut doc = OebDocument::new();

    // 1. Extract metadata from docProps/core.xml
    doc.metadata = extract_metadata(&mut archive, path);

    // 2. Load relationships (for image references)
    let rels = load_relationships(&mut archive);

    // 3. Parse word/document.xml
    let document_xml = read_zip_text(&mut archive, "word/document.xml")?;
    let (html, toc_entries) = parse_document_xml(&document_xml);
    doc.toc = toc_entries;

    // 4. Extract images from word/media/
    let image_names: Vec<String> = archive
        .file_names()
        .filter(|n| n.starts_with("word/media/"))
        .map(|n| n.to_string())
        .collect();

    for img_name in image_names {
        if let Ok(data) = read_zip_bytes(&mut archive, &img_name) {
            let short_name = img_name.strip_prefix("word/media/").unwrap_or(&img_name);
            let mime = match short_name.rsplit('.').next().unwrap_or("") {
                "png" => "image/png",
                "jpg" | "jpeg" => "image/jpeg",
                "gif" => "image/gif",
                "svg" => "image/svg+xml",
                "emf" => "image/x-emf",
                "wmf" => "image/x-wmf",
                _ => "application/octet-stream",
            };
            doc.add_image(short_name, data, mime);
        }
    }

    // 5. Build XHTML with image references resolved
    let xhtml = build_xhtml(&html, &doc.metadata.title);
    doc.add_html("content.xhtml", xhtml);

    // 6. Load styles for potential CSS generation
    if let Ok(styles_xml) = read_zip_text(&mut archive, "word/styles.xml") {
        let css = extract_styles_as_css(&styles_xml);
        if !css.is_empty() {
            doc.add_css("styles.css", css);
        }
    }

    tracing::info!(
        "Read DOCX: {} images, {} TOC entries",
        doc.images.len(),
        doc.toc.len()
    );

    Ok(doc)
}

// ── Writer ──────────────────────────────────────────────────────────────

/// Write an OEB document as a DOCX file.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::CompressionMethod;

    let file = std::fs::File::create(path)?;
    let mut zip = zip::ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

    // [Content_Types].xml
    zip.start_file("[Content_Types].xml", opts)?;
    zip.write_all(content_types_xml(doc).as_bytes())?;

    // _rels/.rels
    zip.start_file("_rels/.rels", opts)?;
    zip.write_all(br#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"#)?;

    // docProps/core.xml
    zip.start_file("docProps/core.xml", opts)?;
    zip.write_all(core_properties_xml(&doc.metadata).as_bytes())?;

    // word/_rels/document.xml.rels
    let mut img_rels = String::new();
    let mut rel_id = 1;
    let mut image_rel_map: HashMap<String, String> = HashMap::new();
    for name in doc.images.keys() {
        let rid = format!("rId{}", rel_id);
        img_rels.push_str(&format!(
            r#"  <Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>"#
        ));
        img_rels.push('\n');
        image_rel_map.insert(name.clone(), rid);
        rel_id += 1;
    }
    zip.start_file("word/_rels/document.xml.rels", opts)?;
    zip.write_all(format!(r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{img_rels}</Relationships>"#).as_bytes())?;

    // word/document.xml
    let document_xml = generate_document_xml(doc);
    zip.start_file("word/document.xml", opts)?;
    zip.write_all(document_xml.as_bytes())?;

    // word/styles.xml (minimal)
    zip.start_file("word/styles.xml", opts)?;
    zip.write_all(minimal_styles_xml().as_bytes())?;

    // word/media/* (images)
    for (name, data) in &doc.images {
        zip.start_file(format!("word/media/{name}"), opts)?;
        zip.write_all(data)?;
    }

    zip.finish()?;
    tracing::info!("Wrote DOCX: {}", path.display());
    Ok(())
}

// ── Document XML Parsing ────────────────────────────────────────────────

fn parse_document_xml(xml: &str) -> (String, Vec<TocEntry>) {
    let mut html = String::new();
    let mut toc = Vec::new();
    let mut reader = quick_xml::Reader::from_str(xml);
    let mut in_paragraph = false;
    let mut in_run = false;
    let mut in_text = false;
    let mut current_text = String::new();
    let mut para_style = String::new();
    let mut run_bold = false;
    let mut run_italic = false;

    loop {
        match reader.read_event() {
            Ok(quick_xml::events::Event::Start(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);
                match local {
                    "p" => {
                        in_paragraph = true;
                        para_style.clear();
                        current_text.clear();
                    }
                    "r" => in_run = true,
                    "t" => in_text = true,
                    "pStyle" => {
                        for attr in e.attributes().flatten() {
                            if attr.key.as_ref() == b"w:val" || attr.key.as_ref() == b"val" {
                                para_style = String::from_utf8_lossy(&attr.value).to_string();
                            }
                        }
                    }
                    _ => {}
                }
            }
            Ok(quick_xml::events::Event::Empty(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);
                match local {
                    "b" => run_bold = true,
                    "i" => run_italic = true,
                    "br" => current_text.push_str("<br/>"),
                    "pStyle" => {
                        for attr in e.attributes().flatten() {
                            if attr.key.as_ref() == b"w:val" || attr.key.as_ref() == b"val" {
                                para_style = String::from_utf8_lossy(&attr.value).to_string();
                            }
                        }
                    }
                    _ => {}
                }
            }
            Ok(quick_xml::events::Event::Text(ref e)) => {
                if in_text && in_run {
                    let text = e.unescape().unwrap_or_default().to_string();
                    if run_bold && run_italic {
                        current_text.push_str(&format!("<strong><em>{text}</em></strong>"));
                    } else if run_bold {
                        current_text.push_str(&format!("<strong>{text}</strong>"));
                    } else if run_italic {
                        current_text.push_str(&format!("<em>{text}</em>"));
                    } else {
                        current_text.push_str(&text);
                    }
                }
            }
            Ok(quick_xml::events::Event::End(ref e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local = name.rsplit(':').next().unwrap_or(&name);
                match local {
                    "p" => {
                        if !current_text.trim().is_empty() {
                            let tag = match para_style.as_str() {
                                "Heading1" | "heading1" | "Title" => {
                                    toc.push(TocEntry {
                                        title: strip_html_tags(&current_text),
                                        href: "content.xhtml".into(),
                                        children: Vec::new(),
                                    });
                                    "h1"
                                }
                                "Heading2" | "heading2" | "Subtitle" => {
                                    toc.push(TocEntry {
                                        title: strip_html_tags(&current_text),
                                        href: "content.xhtml".into(),
                                        children: Vec::new(),
                                    });
                                    "h2"
                                }
                                "Heading3" | "heading3" => "h3",
                                _ => "p",
                            };
                            html.push_str(&format!("<{tag}>{}</{tag}>\n", current_text.trim()));
                        }
                        in_paragraph = false;
                    }
                    "r" => {
                        in_run = false;
                        run_bold = false;
                        run_italic = false;
                    }
                    "t" => in_text = false,
                    _ => {}
                }
            }
            Ok(quick_xml::events::Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
    }

    (html, toc)
}

fn strip_html_tags(s: &str) -> String {
    RE_STRIP_TAGS
        .replace_all(s, "")
        .trim()
        .to_string()
}

// ── Document XML Generation ─────────────────────────────────────────────

fn generate_document_xml(doc: &OebDocument) -> String {
    let strip_tags = &*RE_STRIP_TAGS;
    let heading_re = &*RE_HEADING;
    let para_re = &*RE_PARA;
    let bold_re = &*RE_BOLD;
    let italic_re = &*RE_ITALIC;

    let mut body = String::new();

    for name in &doc.spine {
        let html = match doc.html_files.get(name) {
            Some(h) => h,
            None => continue,
        };

        for cap in heading_re.captures_iter(html) {
            let level: u8 = cap[1].parse().unwrap_or(1);
            let text = strip_tags.replace_all(&cap[2], "").to_string();
            let style = format!("Heading{level}");
            body.push_str(&format!(
                r#"<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>"#,
                xml_escape(&text)
            ));
            body.push('\n');
        }

        for cap in para_re.captures_iter(html) {
            let inner = &cap[1];
            body.push_str("<w:p>");

            // Handle bold/italic runs within paragraph
            let mut remaining = inner.to_string();
            // Simple approach: strip formatting tags and output as plain text
            let plain = strip_tags.replace_all(&remaining, "").to_string();
            if !plain.trim().is_empty() {
                body.push_str(&format!(
                    "<w:r><w:t xml:space=\"preserve\">{}</w:t></w:r>",
                    xml_escape(plain.trim())
                ));
            }

            body.push_str("</w:p>\n");
        }
    }

    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<w:body>
{body}
</w:body>
</w:document>"#
    )
}

// ── Metadata ────────────────────────────────────────────────────────────

fn extract_metadata(archive: &mut ZipArchive<std::fs::File>, path: &Path) -> Metadata {
    let mut m = Metadata::new(
        path.file_stem().and_then(|s| s.to_str()).unwrap_or("Untitled"),
    );

    if let Ok(core) = read_zip_text(archive, "docProps/core.xml") {
        let title_re = &*RE_DC_TITLE;
        let creator_re = &*RE_DC_CREATOR;
        let desc_re = &*RE_DC_DESC;
        let lang_re = &*RE_DC_LANG;

        if let Some(cap) = title_re.captures(&core) {
            let t = cap[1].trim().to_string();
            if !t.is_empty() { m.title = t; }
        }
        if let Some(cap) = creator_re.captures(&core) {
            m.authors = vec![cap[1].trim().to_string()];
        }
        if let Some(cap) = desc_re.captures(&core) {
            m.description = Some(cap[1].trim().to_string());
        }
        if let Some(cap) = lang_re.captures(&core) {
            m.language = Some(cap[1].trim().to_string());
        }
    }

    m
}

fn core_properties_xml(m: &Metadata) -> String {
    let authors = m.authors.first().map(|a| a.as_str()).unwrap_or("");
    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>{}</dc:title>
  <dc:creator>{}</dc:creator>
  <dc:language>{}</dc:language>
</cp:coreProperties>"#,
        xml_escape(&m.title),
        xml_escape(authors),
        m.primary_language(),
    )
}

// ── Styles ──────────────────────────────────────────────────────────────

fn extract_styles_as_css(styles_xml: &str) -> String {
    // Extract basic heading/body styles from styles.xml
    // A full implementation would parse w:style elements and map to CSS
    String::from(
        "h1 { font-size: 24pt; font-weight: bold; margin: 1em 0 0.5em; }\n\
         h2 { font-size: 18pt; font-weight: bold; margin: 0.8em 0 0.4em; }\n\
         h3 { font-size: 14pt; font-weight: bold; margin: 0.6em 0 0.3em; }\n\
         p { margin: 0; text-indent: 1.5em; line-height: 1.6; }\n"
    )
}

fn minimal_styles_xml() -> String {
    r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="48"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="36"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:pPr><w:outlineLvl w:val="2"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/></w:rPr>
  </w:style>
</w:styles>"#.to_string()
}

fn content_types_xml(doc: &OebDocument) -> String {
    let mut overrides = String::new();
    for name in doc.images.keys() {
        let ext = name.rsplit('.').next().unwrap_or("bin");
        let mime = match ext {
            "png" => "image/png",
            "jpg" | "jpeg" => "image/jpeg",
            "gif" => "image/gif",
            _ => "application/octet-stream",
        };
        overrides.push_str(&format!(
            r#"  <Override PartName="/word/media/{name}" ContentType="{mime}"/>"#
        ));
        overrides.push('\n');
    }

    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
{overrides}</Types>"#
    )
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn load_relationships(archive: &mut ZipArchive<std::fs::File>) -> HashMap<String, String> {
    let mut rels = HashMap::new();
    if let Ok(xml) = read_zip_text(archive, "word/_rels/document.xml.rels") {
        let id_re = &*RE_REL_ID;
        for cap in id_re.captures_iter(&xml) {
            rels.insert(cap[1].to_string(), cap[2].to_string());
        }
    }
    rels
}

fn read_zip_text(archive: &mut ZipArchive<std::fs::File>, name: &str) -> Result<String> {
    let mut file = archive.by_name(name).with_context(|| format!("Not in ZIP: {name}"))?;
    let mut content = String::new();
    file.read_to_string(&mut content)?;
    Ok(content)
}

fn read_zip_bytes(archive: &mut ZipArchive<std::fs::File>, name: &str) -> Result<Vec<u8>> {
    let mut file = archive.by_name(name).with_context(|| format!("Not in ZIP: {name}"))?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    Ok(data)
}

fn build_xhtml(body_html: &str, title: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{}</title></head>
<body>
{body_html}
</body>
</html>"#,
        xml_escape(title)
    )
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
