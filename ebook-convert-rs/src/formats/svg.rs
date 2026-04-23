//! SVG reader and writer.
//!
//! Reading: Parse SVG as a single-page visual document, rasterize to image,
//!          and extract any embedded text.
//! Writing: Render OEB document pages as SVG (fixed-layout).
//!
//! Uses resvg/usvg for parsing and rendering, tiny-skia for rasterization.

use anyhow::{Context, Result};
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

use crate::pipeline::document::OebDocument;
use crate::pipeline::metadata::Metadata;

static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
static RE_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<h([1-3])[^>]*>(.*?)</h[1-3]>").unwrap());
static RE_PARA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<p[^>]*>(.*?)</p>").unwrap());
static RE_SVG_TEXT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<text[^>]*>(.*?)</text>").unwrap());

// ── Reader ──────────────────────────────────────────────────────────────

/// Read an SVG file into an OEB document.
///
/// SVGs are treated as single-page fixed-layout documents.
/// Text elements are extracted for searchability, and the SVG
/// is rasterized as a cover/content image.
pub fn read(path: &Path) -> Result<OebDocument> {
    let svg_data = std::fs::read(path).context("Failed to read SVG")?;
    let svg_str = String::from_utf8_lossy(&svg_data);

    let mut doc = OebDocument::new();
    let title = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("SVG Document")
        .to_string();
    doc.metadata = Metadata::new(&title);

    // Extract text from SVG <text> elements for searchability
    let extracted_text = extract_svg_text(&svg_str);

    // Parse and rasterize SVG to PNG using resvg
    let png_data = rasterize_svg(&svg_data)?;

    // Add rasterized image
    doc.add_image("content.png", png_data, "image/png");
    doc.metadata.cover_image = Some("content.png".into());

    // Create XHTML wrapper with the image + extracted text
    let xhtml = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title>
<style>
  body {{ margin: 0; padding: 0; text-align: center; }}
  img {{ max-width: 100%; height: auto; }}
  .sr-only {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }}
</style>
</head>
<body>
  <img src="content.png" alt="{title}"/>
  <div class="sr-only">{extracted_text}</div>
</body>
</html>"#,
        title = xml_escape(&title),
        extracted_text = xml_escape(&extracted_text),
    );

    doc.add_html("content.xhtml", xhtml);

    // Also keep the original SVG as a resource
    doc.html_files
        .insert("original.svg".into(), svg_str.to_string());
    doc.mime_map
        .insert("original.svg".into(), "image/svg+xml".into());

    tracing::info!("Read SVG: {}×{} rasterized", 
        get_svg_dimensions(&svg_data).0,
        get_svg_dimensions(&svg_data).1
    );

    Ok(doc)
}

// ── Writer ──────────────────────────────────────────────────────────────

/// Write an OEB document as SVG.
///
/// Each spine item becomes a page in a multi-page SVG.
/// Text is rendered as SVG <text> elements, images as <image>.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    let page_width = 800.0;
    let page_height = 1200.0;
    let margin = 50.0;
    let line_height = 18.0;
    let font_size_body = 14.0;
    let font_size_h1 = 28.0;
    let font_size_h2 = 20.0;

    let strip_tags = &*RE_STRIP_TAGS;
    let heading_re = &*RE_HEADING;
    let para_re = &*RE_PARA;

    let mut pages: Vec<String> = Vec::new();
    let mut current_elements = Vec::new();
    let mut y = margin + 30.0;

    for name in &doc.spine {
        let html = match doc.html_files.get(name) {
            Some(h) => h,
            None => continue,
        };

        // Headings
        for cap in heading_re.captures_iter(html) {
            let level: u8 = cap[1].parse().unwrap_or(1);
            let text = strip_tags.replace_all(&cap[2], "").trim().to_string();
            if text.is_empty() {
                continue;
            }

            let (size, weight) = match level {
                1 => (font_size_h1, "bold"),
                2 => (font_size_h2, "bold"),
                _ => (16.0, "bold"),
            };

            if level == 1 && !current_elements.is_empty() {
                pages.push(build_svg_page(&current_elements, page_width, page_height));
                current_elements.clear();
                y = margin + 30.0;
            }

            y += size + 10.0;
            current_elements.push(format!(
                r#"  <text x="{margin}" y="{y}" font-size="{size}" font-weight="{weight}" font-family="serif">{}</text>"#,
                xml_escape(&text)
            ));
        }

        // Paragraphs
        for cap in para_re.captures_iter(html) {
            let text = strip_tags.replace_all(&cap[1], "").trim().to_string();
            if text.is_empty() {
                continue;
            }

            // Word wrap at ~70 chars
            let words: Vec<&str> = text.split_whitespace().collect();
            let mut line = String::new();

            for word in words {
                if line.len() + word.len() + 1 > 70 {
                    y += line_height;
                    if y > page_height - margin {
                        pages.push(build_svg_page(&current_elements, page_width, page_height));
                        current_elements.clear();
                        y = margin + 30.0;
                    }
                    current_elements.push(format!(
                        r#"  <text x="{margin}" y="{y}" font-size="{font_size_body}" font-family="serif">{}</text>"#,
                        xml_escape(&line)
                    ));
                    line = word.to_string();
                } else {
                    if !line.is_empty() {
                        line.push(' ');
                    }
                    line.push_str(word);
                }
            }

            if !line.is_empty() {
                y += line_height;
                if y > page_height - margin {
                    pages.push(build_svg_page(&current_elements, page_width, page_height));
                    current_elements.clear();
                    y = margin + 30.0;
                }
                current_elements.push(format!(
                    r#"  <text x="{margin}" y="{y}" font-size="{font_size_body}" font-family="serif">{}</text>"#,
                    xml_escape(&line)
                ));
            }

            y += 8.0; // paragraph spacing
        }
    }

    if !current_elements.is_empty() {
        pages.push(build_svg_page(&current_elements, page_width, page_height));
    }

    // For single-page output, write just the first page
    // For multi-page, concatenate with page breaks
    if pages.len() == 1 {
        std::fs::write(path, &pages[0])?;
    } else {
        // Multi-page SVG using nested <svg> elements
        let total_height = page_height * pages.len() as f64;
        let mut svg = format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{page_width}" height="{total_height}" viewBox="0 0 {page_width} {total_height}">
<style>
  text {{ fill: #1a1a1a; }}
  .page-bg {{ fill: white; stroke: #ddd; stroke-width: 0.5; }}
</style>
"#
        );

        for (i, page_content) in pages.iter().enumerate() {
            let y_offset = i as f64 * page_height;
            svg.push_str(&format!(
                r#"<g transform="translate(0, {y_offset})">
  <rect class="page-bg" width="{page_width}" height="{page_height}"/>
"#
            ));
            // Extract inner elements from the page SVG
            let inner_start = page_content.find("<style>").unwrap_or(0);
            let inner_end = page_content.rfind("</svg>").unwrap_or(page_content.len());
            if let Some(after_style) = page_content[inner_start..inner_end].find("</style>") {
                let elements = &page_content[inner_start + after_style + 8..inner_end];
                svg.push_str(elements);
            }
            svg.push_str("</g>\n");
        }

        svg.push_str("</svg>");
        std::fs::write(path, svg)?;
    }

    tracing::info!("Wrote SVG: {} pages", pages.len());
    Ok(())
}

// ── SVG Helpers ─────────────────────────────────────────────────────────

fn build_svg_page(elements: &[String], width: f64, height: f64) -> String {
    let content = elements.join("\n");
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  text {{ fill: #1a1a1a; }}
</style>
<rect width="{width}" height="{height}" fill="white"/>
{content}
</svg>"#
    )
}

/// Extract text content from SVG <text> elements.
fn extract_svg_text(svg: &str) -> String {
    let re = &*RE_SVG_TEXT;
    let strip = &*RE_STRIP_TAGS;

    re.captures_iter(svg)
        .map(|cap| strip.replace_all(&cap[1], "").trim().to_string())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Rasterize SVG to PNG bytes using resvg + tiny-skia.
fn rasterize_svg(svg_data: &[u8]) -> Result<Vec<u8>> {
    let options = usvg::Options::default();
    let tree = usvg::Tree::from_data(svg_data, &options)
        .context("Failed to parse SVG with usvg")?;

    let size = tree.size();
    let (w, h) = (size.width() as u32, size.height() as u32);

    // Clamp to reasonable dimensions
    let max_dim = 4096u32;
    let scale = if w > max_dim || h > max_dim {
        max_dim as f32 / w.max(h) as f32
    } else {
        1.0
    };

    let pw = (w as f32 * scale) as u32;
    let ph = (h as f32 * scale) as u32;

    let mut pixmap = tiny_skia::Pixmap::new(pw, ph)
        .context("Failed to create pixmap")?;

    // Fill with white background
    pixmap.fill(tiny_skia::Color::WHITE);

    let transform = tiny_skia::Transform::from_scale(scale, scale);
    resvg::render(&tree, transform, &mut pixmap.as_mut());

    // Encode as PNG
    let png_data = pixmap.encode_png().context("Failed to encode PNG")?;

    Ok(png_data)
}

/// Get SVG dimensions from the data.
fn get_svg_dimensions(svg_data: &[u8]) -> (u32, u32) {
    match usvg::Tree::from_data(svg_data, &usvg::Options::default()) {
        Ok(tree) => {
            let size = tree.size();
            (size.width() as u32, size.height() as u32)
        }
        Err(_) => (800, 600),
    }
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
