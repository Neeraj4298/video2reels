#!/usr/bin/env python3
"""
video2reels — Phase 0 Prototype CLI
─────────────────────────────────────
Runs the full 6-stage pipeline on a local file or URL.

Usage:
  python scripts/prototype.py --input video.mp4
  python scripts/prototype.py --url "https://youtube.com/..."
  python scripts/prototype.py --input video.mp4 --stages 1,2,3

All intermediate outputs are cached — re-running skips completed stages.
"""
import sys
import os
import time
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich import print as rprint
from loguru import logger

console = Console()
app = typer.Typer(help="video2reels Phase 0 Prototype CLI")


def _setup_logging(log_level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )


def _print_banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]🎬 video2reels[/bold cyan]  [dim]Phase 0 Prototype[/dim]\n"
        "[dim]Turning long videos into viral short clips[/dim]",
        border_style="cyan",
    ))


def _print_stage_header(n: int, name: str) -> None:
    console.rule(f"[bold yellow]Stage {n}: {name}[/bold yellow]")


def _print_clips_table(clips) -> None:
    table = Table(title="🎯 Selected Clips", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3)
    table.add_column("Start → End", style="cyan", width=15)
    table.add_column("Dur", style="green", width=5)
    table.add_column("Score", style="bold yellow", width=6)
    table.add_column("Hook", style="white", max_width=50)

    for i, clip in enumerate(clips, 1):
        score_color = "green" if clip.score >= 75 else "yellow" if clip.score >= 50 else "red"
        table.add_row(
            str(i),
            f"{clip.start:.1f}s → {clip.end:.1f}s",
            f"{clip.duration:.0f}s",
            f"[{score_color}]{clip.score}[/{score_color}]",
            clip.hook[:50],
        )
    console.print(table)


@app.command()
def main(
    input: str = typer.Option(None, "--input", "-i", help="Local video file path"),
    url: str = typer.Option(None, "--url", "-u", help="Video URL (YouTube, etc.)"),
    stages: str = typer.Option("1,2,3,4,5,6", "--stages", "-s", help="Comma-separated stage numbers to run"),
    project_id: str = typer.Option(None, "--project-id", "-p", help="Project ID (auto-generated if not set)"),
    log_level: str = typer.Option("INFO", "--log-level", help="DEBUG|INFO|WARNING"),
    env_file: str = typer.Option(".env", "--env", help="Path to .env file"),
) -> None:
    """Run the full video2reels pipeline on a local file or URL."""

    _setup_logging(log_level)
    _print_banner()

    # ── Validate input ────────────────────────────────────────────────────────
    if not input and not url:
        console.print("[red]Error:[/red] Provide --input <file> or --url <url>")
        raise typer.Exit(1)

    source = input or url

    # ── Load env ──────────────────────────────────────────────────────────────
    from dotenv import load_dotenv
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)
        logger.info("Loaded env from {}", env_path)
    else:
        logger.warning(".env not found at {}. Using system env vars.", env_path)

    # Re-import config after env load
    from workers import config

    # ── Set up work directories ───────────────────────────────────────────────
    if not project_id:
        import hashlib, datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        project_id = f"project_{ts}"

    work_dir = Path("./work") / project_id
    output_dir = Path(os.getenv("OUTPUT_DIR", "./output"))
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Override OUTPUT_DIR in config module (read by render.py)
    config.OUTPUT_DIR = output_dir

    console.print(f"[dim]Project ID:[/dim] [cyan]{project_id}[/cyan]")
    console.print(f"[dim]Work dir:[/dim]   [cyan]{work_dir}[/cyan]")
    console.print(f"[dim]Output dir:[/dim] [cyan]{output_dir / project_id}[/cyan]")
    console.print()

    active_stages = {int(s.strip()) for s in stages.split(",")}
    pipeline_start = time.time()

    # ── Stage 1: Ingest ───────────────────────────────────────────────────────
    meta = None
    if 1 in active_stages:
        _print_stage_header(1, "Ingestion & Validation")
        from workers.ingest import ingest
        with console.status("[cyan]Probing video…"):
            meta = ingest(source, work_dir)
        console.print(f"  [green]✓[/green] {meta.path.name}  |  {meta.duration/60:.1f} min  |  {meta.width}×{meta.height}  |  {meta.fps} fps")
        console.print()

    # ── Stage 2: Audio ────────────────────────────────────────────────────────
    audio_path = None
    if 2 in active_stages:
        _print_stage_header(2, "Audio Extraction")
        if meta is None:
            # Re-probe if stage 1 was skipped
            from workers.ingest import probe_video
            meta = probe_video(Path(source) if not source.startswith("http") else list((work_dir / "raw").glob("*.mp4"))[-1])
        from workers.audio_extract import extract_audio
        with console.status("[cyan]Extracting audio…"):
            audio_path = extract_audio(meta, work_dir)
        size_mb = audio_path.stat().st_size / 1_048_576
        console.print(f"  [green]✓[/green] {audio_path.name}  |  {size_mb:.1f} MB")
        console.print()

    # ── Stage 3: Transcribe ───────────────────────────────────────────────────
    transcript = None
    if 3 in active_stages:
        _print_stage_header(3, f"Transcription (whisper/{os.getenv('WHISPER_MODEL','base')})")
        if audio_path is None:
            audio_path = work_dir / "audio" / "audio.wav"
        from workers.transcribe import transcribe
        with console.status(f"[cyan]Transcribing with Whisper {os.getenv('WHISPER_MODEL','base')}… (may take a few minutes)"):
            transcript = transcribe(audio_path, work_dir)
        console.print(f"  [green]✓[/green] Language: [bold]{transcript.language}[/bold]  |  {len(transcript.segments)} segments  |  {len(transcript.all_words)} words")
        console.print()

    # ── Stage 4: Clip selection ───────────────────────────────────────────────
    clips = None
    if 4 in active_stages:
        _print_stage_header(4, f"Clip Selection (LLM: {os.getenv('LLM_PROVIDER','gemini')})")
        if transcript is None:
            from workers.transcribe import Transcript
            transcript = Transcript.from_dict(
                json.loads((work_dir / "transcripts" / "transcript.json").read_text())
            )
        from workers.select_clips import select_clips
        with console.status("[cyan]LLM analyzing transcript…"):
            clips = select_clips(transcript, work_dir)
        _print_clips_table(clips)
        console.print()

    # ── Stage 5: Reframe ─────────────────────────────────────────────────────
    reframes = None
    if 5 in active_stages:
        _print_stage_header(5, "Vertical Reframing (9:16 center crop)")
        if meta is None:
            from workers.ingest import probe_video
            mp4 = list((work_dir / "raw").glob("*.mp4"))
            meta = probe_video(mp4[-1] if mp4 else Path(source))
        if clips is None:
            clips_data = json.loads((work_dir / "clips" / "clips.json").read_text())
            from workers.select_clips import Clip, ScoreBreakdown
            clips = [
                Clip(
                    start=c["start"], end=c["end"],
                    hook=c["hook"], title=c["title"],
                    score=c["score"],
                    score_breakdown=ScoreBreakdown(**c["score_breakdown"]),
                    reason=c["reason"],
                )
                for c in clips_data
            ]
        from workers.reframe import reframe_all_clips
        reframes = reframe_all_clips(clips, meta.path, work_dir, meta.width, meta.height, meta.fps)
        console.print(f"  [green]✓[/green] Reframe plans computed for {len(reframes)} clips (center-crop mode)")
        console.print()

    # ── Stage 6: Render ───────────────────────────────────────────────────────
    if 6 in active_stages:
        _print_stage_header(6, "Caption Render + FFmpeg Export")
        if reframes is None or clips is None or transcript is None or meta is None:
            console.print("[red]Stages 1-5 must complete before stage 6. Run without --stages or include all.[/red]")
            raise typer.Exit(1)

        from workers.render import render_all_clips
        results = render_all_clips(
            clips=clips, reframes=reframes, transcript=transcript,
            meta=meta, work_dir=work_dir, project_id=project_id,
        )

        console.print()
        table = Table(title="✅ Final Output", header_style="bold green")
        table.add_column("Clip", width=4)
        table.add_column("File", style="cyan")
        table.add_column("Duration", style="green", width=8)
        table.add_column("Size", style="yellow", width=8)
        table.add_column("Render time", width=10)
        for res in results:
            table.add_row(
                str(results.index(res) + 1),
                res.output_path.name,
                f"{res.duration:.0f}s",
                f"{res.size_mb:.1f} MB",
                f"{res.render_time:.1f}s",
            )
        console.print(table)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = time.time() - pipeline_start
    console.print()
    console.print(Panel(
        f"[bold green]Pipeline complete[/bold green] in [cyan]{total:.0f}s[/cyan]\n"
        f"Output: [cyan]{output_dir / project_id}[/cyan]",
        border_style="green",
    ))


if __name__ == "__main__":
    app()
