//! Plain text and Markdown input/output.

use anyhow::Result;
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

static RE_H1: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^# (.+)$").unwrap());
static RE_H2: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^## (.+)$").unwrap());
static RE_H3: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^### (.+)$").unwrap());
static RE_BOLD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\*\*(.+?)\*\*").unwrap());
static RE_ITALIC: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\*(.+?)\*").unwrap());use crate::pipeline::document::OebDocument;
use crate::pipeline::metadata::Metadata;

/// Read a text/markdown file into an OEB document.
pub fn read(path: &Path) -> Result<OebDocument> {
    let content = std::fs::read_to_string(path)?;
    let mut doc = OebDocument::new();

    let title = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("Untitled")
        .to_string();
    doc.metadata = Metadata::new(&title);

    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("txt");
    let html = if ext == "md" || ext == "markdown" {
        markdown_to_xhtml(&content, &title)
    } else {
        text_to_xhtml(&content, &title)
    };

    doc.add_html("content.xhtml", html);
    Ok(doc)
}

/// Write an OEB document as plain text.
pub fn write(doc: &OebDocument, path: &Path) -> Result<()> {
    let text = doc.plain_text();
    std::fs::write(path, text)?;
    Ok(())
}

fn text_to_xhtml(text: &str, title: &str) -> String {
    let paragraphs: String = text
        .split("\n\n")
        .filter(|p| !p.trim().is_empty())
        .map(|p| format!("<p>{}</p>", xml_escape(p.trim())))
        .collect::<Vec<_>>()
        .join("\n");

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
<h1>{title}</h1>
{paragraphs}
</body>
</html>"#
    )
}

fn markdown_to_xhtml(md: &str, title: &str) -> String {
    let re_h1 = &*RE_H1;
    let re_h2 = &*RE_H2;
    let re_h3 = &*RE_H3;
    let re_bold = &*RE_BOLD;
    let re_italic = &*RE_ITALIC;

    let mut html = String::new();
    let mut in_paragraph = false;

    for line in md.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            if in_paragraph {
                html.push_str("</p>\n");
                in_paragraph = false;
            }
            continue;
        }

        let converted = if let Some(cap) = re_h1.captures(trimmed) {
            format!("<h1>{}</h1>", xml_escape(&cap[1]))
        } else if let Some(cap) = re_h2.captures(trimmed) {
            format!("<h2>{}</h2>", xml_escape(&cap[1]))
        } else if let Some(cap) = re_h3.captures(trimmed) {
            format!("<h3>{}</h3>", xml_escape(&cap[1]))
        } else {
            let escaped = xml_escape(trimmed);
            let bolded = re_bold.replace_all(&escaped, "<strong>$1</strong>");
            let italicized = re_italic.replace_all(&bolded, "<em>$1</em>");
            if !in_paragraph {
                in_paragraph = true;
                format!("<p>{}", italicized)
            } else {
                format!(" {}", italicized)
            }
        };
        html.push_str(&converted);
        html.push('\n');
    }
    if in_paragraph {
        html.push_str("</p>\n");
    }

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
{html}
</body>
</html>"#
    )
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
