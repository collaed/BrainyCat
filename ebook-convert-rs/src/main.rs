//! CLI entry point: ebook-convert input.epub output.mobi [options]

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing_subscriber;

#[derive(Parser)]
#[command(name = "ebook-convert", about = "Convert between ebook formats")]
struct Cli {
    /// Input file path
    input: PathBuf,

    /// Output file path (format detected from extension)
    output: PathBuf,

    /// Extra CSS to inject
    #[arg(long)]
    extra_css: Option<String>,

    /// Base font size in points
    #[arg(long, default_value = "12.0")]
    base_font_size: f32,

    /// Chapter detection XPath
    #[arg(long, default_value = "//*[re:test(name(), '^h[12]$', 'i')]")]
    chapter_xpath: String,

    /// Enable heuristic processing (dehyphenation, paragraph detection)
    #[arg(long)]
    heuristics: bool,

    /// Output profile (kindle, kobo, generic, tablet, phone)
    #[arg(long, default_value = "generic")]
    output_profile: String,

    /// Skip bad records/files instead of aborting (produces degraded output)
    #[arg(long)]
    lenient: bool,

    /// Output JSON summary to stderr (for programmatic integration)
    #[arg(long)]
    json_summary: bool,

    /// Verbose logging
    #[arg(short, long)]
    verbose: bool,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    tracing_subscriber::fmt()
        .with_max_level(if cli.verbose {
            tracing::Level::DEBUG
        } else {
            tracing::Level::INFO
        })
        .init();

    let options = ebook_convert::pipeline::ConvertOptions {
        extra_css: cli.extra_css,
        base_font_size: cli.base_font_size,
        chapter_xpath: cli.chapter_xpath,
        heuristics: cli.heuristics,
        output_profile: cli.output_profile,
        lenient: cli.lenient,
    };

    ebook_convert::convert(&cli.input, &cli.output, &options)?;

    if cli.json_summary {
        let out_size = std::fs::metadata(&cli.output).map(|m| m.len()).unwrap_or(0);
        let summary = serde_json::json!({
            "status": "ok",
            "input": cli.input.display().to_string(),
            "output": cli.output.display().to_string(),
            "output_size": out_size,
        });
        eprintln!("{}", summary);
    }

    tracing::info!(
        "Converted {} → {}",
        cli.input.display(),
        cli.output.display()
    );
    Ok(())
}
