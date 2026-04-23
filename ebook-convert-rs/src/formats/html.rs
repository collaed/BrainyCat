//! HTML input/output — read a standalone HTML file, write HTML from OEB.

use anyhow::Result;
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

static RE_TITLE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<title>([^<]+)</title>").unwrap());use crate::pipeline::document::OebDocument;
use crate::pipeline::metadata::Metadata;

/// Read an HTML file into an OEB document (single-file book).
pub fn read(path: &Path) -> Result<OebDocument> {
    // LP#1188843: Some HTML files contain invalid UTF-8 bytes.
    // Read as bytes and fall back to lossy decoding.
    let bytes = std::fs::read(path)?;
    let content = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            tracing::warn!("Invalid UTF-8 in {}, using lossy decoding", path.display());
            String::from_utf8_lossy(e.as_bytes()).into_owned()
        }
    };
    let mut doc = OebDocument::new();

    // Extract title from <title> tag
    let title = RE_TITLE
        .captures(&content)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_string())
        .unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("Untitled")
                .to_string()
        });

    doc.metadata = Metadata::new(&title);
    doc.add_html("content.xhtml", ensure_xhtml(&content));

    Ok(doc)
}

/// Write an OEB document as a single HTML file.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    let mut html = String::from("<!DOCTYPE html>\n<html>\n<head>\n");
    html.push_str(&format!(
        "<title>{}</title>\n",
        doc.metadata.title
    ));

    // Inline all stylesheets
    for css in doc.stylesheets.values() {
        html.push_str(&format!("<style>\n{css}\n</style>\n"));
    }
    html.push_str("</head>\n<body>\n");

    // Concatenate all spine items
    for name in &doc.spine {
        if let Some(content) = doc.html_files.get(name) {
            // Extract body content only
            if let Some(body_start) = content.find("<body") {
                if let Some(body_end) = content[body_start..].find('>') {
                    let after_body = body_start + body_end + 1;
                    if let Some(close) = content.rfind("</body>") {
                        html.push_str(&content[after_body..close]);
                        html.push_str("\n<hr/>\n");
                    }
                }
            }
        }
    }

    html.push_str("</body>\n</html>");
    std::fs::write(path, html)?;
    Ok(())
}

/// Ensure content is valid XHTML (basic fixup).
fn ensure_xhtml(html: &str) -> String {
    // If it already has an XML declaration or xhtml namespace, assume it's fine
    if html.contains("xmlns=\"http://www.w3.org/1999/xhtml\"") {
        return html.to_string();
    }

    // Wrap in XHTML boilerplate
    let body = if let Some(start) = html.find("<body") {
        if let Some(end) = html.rfind("</body>") {
            &html[start..end + 7]
        } else {
            html
        }
    } else {
        html
    };

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Content</title></head>
{body}
</html>"#
    )
}
