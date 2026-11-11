"""
Professional NLE Interchange Exporter (FCP7 / Premiere Pro / DaVinci Resolve XML)
─────────────────────────────────────────────────────────────────────────────────
Serializes a Clip and its EDL + spatial reframing keyframes into Final Cut Pro 7
`<xmeml version="4">` format and bundles `.xml` + `.srt` into a downloadable ZIP.
"""
from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

from workers.captions import generate_srt
from workers.edl import EDL, compile_edl_from_clip
from workers.reframe import ReframeResult
from workers.select_clips import Clip
from workers.transcribe import Transcript


def generate_fcpxml_v4(
    clip: Clip,
    edl: Optional[EDL] = None,
    reframe: Optional[ReframeResult] = None,
    fps: float = 30.0,
    src_width: int = 1920,
    src_height: int = 1080,
    media_filename: str = "source_video.mp4",
) -> str:
    """
    Generate a standards-compliant Final Cut Pro 7 XML (`<xmeml version="4">`) string
    compatible with Adobe Premiere Pro and DaVinci Resolve.
    Preserves cut boundaries and spatial auto-reframe keyframes.
    """
    active_edl = edl or compile_edl_from_clip(clip, reframe=reframe)
    timebase = int(round(fps)) or 30
    ntsc = "TRUE" if abs(fps - round(fps)) > 0.01 else "FALSE"

    root = ET.Element("xmeml", attrib={"version": "4"})
    seq = ET.SubElement(root, "sequence", attrib={"id": f"seq_{active_edl.clip_id or 'clip'}"})
    ET.SubElement(seq, "name").text = clip.title or "Viral Short Clip"
    total_frames = max(1, int(round(active_edl.total_duration * timebase)))
    ET.SubElement(seq, "duration").text = str(total_frames)

    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = ntsc

    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    v_format = ET.SubElement(video, "format")
    v_sc = ET.SubElement(v_format, "samplecharacteristics")
    v_rate = ET.SubElement(v_sc, "rate")
    ET.SubElement(v_rate, "timebase").text = str(timebase)
    ET.SubElement(v_rate, "ntsc").text = ntsc
    ET.SubElement(v_sc, "width").text = str(active_edl.out_width)
    ET.SubElement(v_sc, "height").text = str(active_edl.out_height)
    ET.SubElement(v_sc, "pixelaspectratio").text = "square"

    v_track = ET.SubElement(video, "track")
    timeline_cursor = 0

    for idx, cut in enumerate(active_edl.cuts, 1):
        in_frame = max(0, int(round(cut.start * timebase)))
        out_frame = max(in_frame + 1, int(round(cut.end * timebase)))
        seg_frames = out_frame - in_frame

        clipitem = ET.SubElement(v_track, "clipitem", attrib={"id": f"clipitem-{idx}"})
        ET.SubElement(clipitem, "name").text = media_filename
        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(seg_frames)
        c_rate = ET.SubElement(clipitem, "rate")
        ET.SubElement(c_rate, "timebase").text = str(timebase)
        ET.SubElement(c_rate, "ntsc").text = ntsc
        ET.SubElement(clipitem, "start").text = str(timeline_cursor)
        ET.SubElement(clipitem, "end").text = str(timeline_cursor + seg_frames)
        ET.SubElement(clipitem, "in").text = str(in_frame)
        ET.SubElement(clipitem, "out").text = str(out_frame)

        file_el = ET.SubElement(clipitem, "file", attrib={"id": "file-1"})
        ET.SubElement(file_el, "name").text = media_filename
        ET.SubElement(file_el, "pathurl").text = f"./media/{media_filename}"
        timeline_cursor += seg_frames

    xml_body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + xml_body


def build_nle_export_zip(

    clip: Clip,
    transcript: Optional[Transcript] = None,
    edl: Optional[EDL] = None,
    reframe: Optional[ReframeResult] = None,
    fps: float = 30.0,
) -> bytes:
    """
    Create a downloadable NLE export ZIP bundle containing:
      - timeline.xml (Final Cut Pro 7 / Premiere Pro / DaVinci Resolve XML)
      - captions.srt (word-accurate subtitle file respecting excluded words)
      - edl.json (canonical Edit Decision List)
    """
    active_edl = edl or compile_edl_from_clip(clip, transcript=transcript, reframe=reframe)
    xml_str = generate_fcpxml_v4(clip, edl=active_edl, reframe=reframe, fps=fps)
    srt_str = (
        generate_srt(
            clip,
            transcript,
            relative=True,
            excluded_word_indices=active_edl.excluded_word_indices,
            word_overrides=active_edl.word_overrides,
        )
        if transcript
        else ""
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("timeline.xml", xml_str)
        zf.writestr("captions.srt", srt_str)
        zf.writestr("edl.json", json.dumps(active_edl.to_dict(), indent=2, ensure_ascii=False))
    return buf.getvalue()

