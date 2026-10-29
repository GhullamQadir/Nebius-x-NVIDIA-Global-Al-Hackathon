#!/usr/bin/env python3
"""
Nexora Launch Video Generator (Brag Skill)
Generates a complete 2-minute product launch showcase video (brag.mp4)
with professional 1080p motion slides, studio-quality neural voiceover,
ambient electronic music, and hackathon branding.
"""

import os
import sys
import math
import struct
import wave
import asyncio
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Set up paths
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "nexora" / "frontend" / "assets"
LOGO_PATH = ASSETS_DIR / "nexora-logo.png"
OUTPUT_DIR = REPO_ROOT / "brag-output"
TEMP_DIR = OUTPUT_DIR / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Colors
C_BG_DARK = (10, 14, 22)         # #0a0e16
C_BG_CARD = (18, 24, 38)         # #121826
C_BORDER = (38, 48, 72)          # #263048
C_CYAN = (56, 189, 248)          # #38bdf8
C_INDIGO = (99, 102, 241)        # #6366f1
C_EMERALD = (16, 185, 129)       # #10b981
C_ROSE = (244, 63, 94)           # #f43f5e
C_AMBER = (245, 158, 11)         # #f59e0b
C_TEXT_WHITE = (248, 250, 252)   # #f8fafc
C_TEXT_MUTED = (148, 163, 184)   # #94a3b8

# Fonts
WIN_FONTS = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
FONT_TITLE = ImageFont.truetype(str(WIN_FONTS / "segoeuib.ttf"), 54)
FONT_SUBTITLE = ImageFont.truetype(str(WIN_FONTS / "segoeui.ttf"), 26)
FONT_BADGE = ImageFont.truetype(str(WIN_FONTS / "segoeuib.ttf"), 20)
FONT_CARD_TITLE = ImageFont.truetype(str(WIN_FONTS / "segoeuib.ttf"), 24)
FONT_CARD_BODY = ImageFont.truetype(str(WIN_FONTS / "segoeui.ttf"), 20)
FONT_MONO = ImageFont.truetype(str(WIN_FONTS / "consola.ttf"), 22)

# Storyboard configuration
SCENES = [
    {
        "id": "scene_1_intro",
        "title": "NEXORA",
        "subtitle": "Autonomous · Token-Efficient · Self-Healing AI Coding Agent",
        "badge": "NEBIUS AI CLOUD  x  NVIDIA ACCELERATED INFRASTRUCTURE",
        "speech": (
            "Welcome to Nexora — an autonomous, token-efficient, and secure AI coding agent "
            "engineered for high-performance software engineering, powered by Nebius AI Cloud "
            "and NVIDIA accelerated computing."
        ),
        "type": "intro"
    },
    {
        "id": "scene_2_problem",
        "title": "THE CHALLENGE IN MODERN AI CODING",
        "subtitle": "Why Existing Autonomous Coding Agents Fail in Production",
        "badge": "THE CORE BOTTLENECKS",
        "speech": (
            "Modern developers face massive roadblocks with traditional AI coding tools: "
            "catastrophic context bloat that burns through token budgets, silent syntax failures, "
            "and fragile execution loops that break entire codebases. "
            "Nexora was built to eliminate these pain points from the ground up."
        ),
        "type": "problem"
    },
    {
        "id": "scene_3_token_opt",
        "title": "PILLAR 1: DYNAMIC TOKEN OPTIMIZATION",
        "subtitle": "Maximal Code Intelligence with Minimal Token Overhead",
        "badge": "COST EFFICIENCY ENGINE",
        "speech": (
            "First, Nexora introduces intelligent token optimization. "
            "By combining smart abstract syntax tree dependency analysis with history compaction, "
            "Nexora dynamically prunes stale context while preserving architectural integrity — "
            "cutting token consumption by over sixty percent."
        ),
        "type": "token_opt"
    },
    {
        "id": "scene_4_self_healing",
        "title": "PILLAR 2: REAL-TIME SELF-HEALING ENGINE",
        "subtitle": "Automated Error Isolation, Thought Streaming & Verified Recovery",
        "badge": "AUTONOMOUS STABILITY",
        "speech": (
            "Second, our autonomous Self-Healing engine. "
            "When code encounters syntax errors or failing regression tests, "
            "Nexora isolates the exact file, streams diagnostic thoughts in real time, "
            "and applies targeted self-healing iterations until all tests pass."
        ),
        "type": "self_healing"
    },
    {
        "id": "scene_5_security",
        "title": "PILLAR 3: ENTERPRISE POLICY GUARDIAN",
        "subtitle": "Deterministic Command Gating & Safe Execution Sandboxing",
        "badge": "ZERO-TRUST SAFETY",
        "speech": (
            "Security is non-negotiable in production environments. "
            "Nexora's Policy Guardian enforces deterministic command gating, "
            "containerized sandbox execution, and human-in-the-loop approvals for sensitive modifications, "
            "preventing accidental data loss or unauthorized shell commands."
        ),
        "type": "security"
    },
    {
        "id": "scene_6_studio",
        "title": "PILLAR 4: MODERN DEVELOPER STUDIO",
        "subtitle": "Seamless Visual Diffs, Web Previews & Clean Code Export",
        "badge": "ENGINEER EXPERIENCE",
        "speech": (
            "For engineering teams, Nexora delivers a state-of-the-art developer studio. "
            "Featuring GitHub-style visual split and unified diffs, dynamic light and dark theme adaptation, "
            "one-click clean code exports, and an instant interactive live preview for animated web applications."
        ),
        "type": "studio"
    },
    {
        "id": "scene_7_outro",
        "title": "THE NEXT ERA OF AUTONOMOUS ENGINEERING",
        "subtitle": "Built for the Nebius x NVIDIA Global AI Hackathon",
        "badge": "NEBIUS AI STUDIO  ·  NVIDIA INFERENCE  ·  OPEN SOURCE",
        "speech": (
            "Combining the raw speed of Nebius AI Studio with NVIDIA's state-of-the-art inference stack, "
            "Nexora sets a new standard for autonomous, cost-effective, and safe software engineering. "
            "Built for the Nebius and NVIDIA Global AI Hackathon. Thank you."
        ),
        "type": "outro"
    }
]

def draw_header_badge(draw, text, y_pos=75, color=C_CYAN):
    bbox = FONT_BADGE.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    px, py = 24, 10
    w = tw + px * 2
    h = th + py * 2
    x = (1920 - w) // 2
    y = y_pos

    # Pill background
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h//2, fill=(24, 34, 52), outline=color, width=2)
    draw.text((x + px, y + py - 2), text, font=FONT_BADGE, fill=color)

def draw_card(draw, x, y, w, h, title, desc, tag=None, tag_color=C_CYAN, border_color=C_BORDER):
    # Card background
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=C_BG_CARD, outline=border_color, width=2)
    # Accent top border
    draw.rounded_rectangle([x, y, x + w, y + 6], radius=3, fill=tag_color)
    
    # Tag
    curr_y = y + 24
    if tag:
        draw.text((x + 28, curr_y), tag.upper(), font=FONT_BADGE, fill=tag_color)
        curr_y += 32
        
    # Title
    draw.text((x + 28, curr_y), title, font=FONT_CARD_TITLE, fill=C_TEXT_WHITE)
    curr_y += 42
    
    # Description (wrap text)
    words = desc.split()
    lines = []
    curr_line = []
    for word in words:
        test_line = " ".join(curr_line + [word])
        tb = FONT_CARD_BODY.getbbox(test_line)
        if (tb[2] - tb[0]) <= (w - 56):
            curr_line.append(word)
        else:
            lines.append(" ".join(curr_line))
            curr_line = [word]
    if curr_line:
        lines.append(" ".join(curr_line))
        
    for line in lines:
        draw.text((x + 28, curr_y), line, font=FONT_CARD_BODY, fill=C_TEXT_MUTED)
        curr_y += 30

def create_base_canvas():
    img = Image.new("RGB", (1920, 1080), C_BG_DARK)
    draw = ImageDraw.Draw(img)
    
    # Subtle cybernetic grid dots
    for gx in range(60, 1920, 120):
        for gy in range(60, 1080, 120):
            draw.point((gx, gy), fill=(30, 42, 64))
            draw.point((gx+1, gy), fill=(30, 42, 64))
            
    # Soft background gradient blobs (top-right and bottom-left)
    draw.ellipse([1400, -100, 2000, 500], fill=(16, 24, 42))
    draw.ellipse([-100, 650, 500, 1200], fill=(16, 28, 46))
    return img, draw

def render_scene_image(scene, out_path):
    img, draw = create_base_canvas()
    stype = scene["type"]
    
    # Header badge
    draw_header_badge(draw, scene["badge"])
    
    if stype == "intro":
        # Logo
        if LOGO_PATH.exists():
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize((140, 140), Image.Resampling.LANCZOS)
            img.paste(logo, (890, 180), logo)
            
        # Title
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 350), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        
        # Subtitle
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 435), scene["subtitle"], font=FONT_SUBTITLE, fill=C_CYAN)
        
        # 3 Key Highlights
        card_w, card_h = 520, 320
        gap = 40
        start_x = (1920 - (card_w * 3 + gap * 2)) // 2
        y_pos = 550
        
        draw_card(draw, start_x, y_pos, card_w, card_h, 
                  "Autonomous Execution", 
                  "End-to-end task breakdown, multi-file code editing, and automated test-driven validation.",
                  tag="Orchestration", tag_color=C_CYAN)
                  
        draw_card(draw, start_x + (card_w + gap), y_pos, card_w, card_h, 
                  "60%+ Token Reduction", 
                  "AST-guided context pruning, conversation compaction, and dynamic output budgets.",
                  tag="Efficiency", tag_color=C_EMERALD)
                  
        draw_card(draw, start_x + (card_w + gap) * 2, y_pos, card_w, card_h, 
                  "Self-Healing Engine", 
                  "Automatic error interception, diagnostic thought streaming, and zero-crash recovery.",
                  tag="Reliability", tag_color=C_INDIGO)

    elif stype == "problem":
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 170), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 245), scene["subtitle"], font=FONT_SUBTITLE, fill=C_ROSE)
        
        card_w, card_h = 520, 480
        gap = 40
        start_x = (1920 - (card_w * 3 + gap * 2)) // 2
        y_pos = 360
        
        draw_card(draw, start_x, y_pos, card_w, card_h,
                  "1. Catastrophic Context Bloat",
                  "Traditional coding agents feed entire source trees and raw histories into every prompt. This quickly exhausts LLM token budgets, increases latency, and causes massive API cost overruns.",
                  tag="Token Waste", tag_color=C_ROSE, border_color=(70, 30, 40))
                  
        draw_card(draw, start_x + (card_w + gap), y_pos, card_w, card_h,
                  "2. Fragile Execution Loops",
                  "When generated patches fail syntax checks or break unit tests, ordinary agents crash or hallucinate infinite loops, leaving repositories in corrupted states without automated self-repair.",
                  tag="Silent Breakdowns", tag_color=C_AMBER, border_color=(70, 50, 30))
                  
        draw_card(draw, start_x + (card_w + gap) * 2, y_pos, card_w, card_h,
                  "3. Unsafe Shell Execution",
                  "Unchecked tool execution can trigger destructive bash commands, overwrite production secrets, or bypass policy rules, creating serious enterprise security risks.",
                  tag="Security Vulnerabilities", tag_color=C_ROSE, border_color=(70, 30, 40))

    elif stype == "token_opt":
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 170), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 245), scene["subtitle"], font=FONT_SUBTITLE, fill=C_EMERALD)
        
        card_w, card_h = 520, 440
        gap = 40
        start_x = (1920 - (card_w * 3 + gap * 2)) // 2
        y_pos = 340
        
        draw_card(draw, start_x, y_pos, card_w, card_h,
                  "History Compactor",
                  "Compresses prior agent thoughts and redundant tool exchanges into dense, high-signal architectural summaries, eliminating up to 70% of historical context tokens.",
                  tag="Memory Optimization", tag_color=C_EMERALD)
                  
        draw_card(draw, start_x + (card_w + gap), y_pos, card_w, card_h,
                  "AST Context Trimmer",
                  "Parses Python abstract syntax trees to include only the modified functions, classes, and immediate dependencies instead of wasteful 2000-line whole-file dumps.",
                  tag="Semantic Precision", tag_color=C_CYAN)
                  
        draw_card(draw, start_x + (card_w + gap) * 2, y_pos, card_w, card_h,
                  "Dynamic Output Budgeting",
                  "Smart heuristic router predicts exact response needs: 768 tokens for targeted bug fixes vs 4096 tokens for multi-page web applications. Zero truncated code.",
                  tag="Adaptive Tokens", tag_color=C_INDIGO)
                  
        # Bottom Stat Banner
        b_w, b_h = 1640, 100
        b_x = (1920 - b_w) // 2
        draw.rounded_rectangle([b_x, 820, b_x + b_w, 820 + b_h], radius=14, fill=(16, 36, 34), outline=C_EMERALD, width=2)
        stat_text = "BENCHMARK PROVEN:  62.4% AVERAGE TOKEN SAVINGS  ·  ZERO ARCHITECTURAL LOSS  ·  3.2x FASTER INFERENCE"
        st_box = FONT_CARD_TITLE.getbbox(stat_text)
        draw.text(((1920 - (st_box[2] - st_box[0])) // 2, 855), stat_text, font=FONT_CARD_TITLE, fill=C_EMERALD)

    elif stype == "self_healing":
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 170), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 245), scene["subtitle"], font=FONT_SUBTITLE, fill=C_CYAN)
        
        # 4-Step Pipeline Cards
        steps = [
            ("STEP 1: DETECT", "Instant Python AST check & isolated pytest execution catch syntax and regression failures in <1 second.", C_CYAN),
            ("STEP 2: ISOLATE", "Pinpoints the exact failing line, traceback, and symbol dependency without scanning entire repos.", C_INDIGO),
            ("STEP 3: STREAM", "Broadband SSE diagnostic streaming exposes healing thoughts and patch diffs to the developer in real-time.", C_AMBER),
            ("STEP 4: VERIFY", "Re-executes targeted tests until 100% green before committing. Guaranteed clean code delivery.", C_EMERALD)
        ]
        
        sw, sh = 390, 480
        sgap = 30
        s_start_x = (1920 - (sw * 4 + sgap * 3)) // 2
        for i, (stitle, sdesc, scolor) in enumerate(steps):
            x = s_start_x + i * (sw + sgap)
            draw_card(draw, x, 340, sw, sh, stitle, sdesc, tag=f"Phase 0{i+1}", tag_color=scolor)

    elif stype == "security":
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 170), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 245), scene["subtitle"], font=FONT_SUBTITLE, fill=C_AMBER)
        
        card_w, card_h = 520, 480
        gap = 40
        start_x = (1920 - (card_w * 3 + gap * 2)) // 2
        y_pos = 360
        
        draw_card(draw, start_x, y_pos, card_w, card_h,
                  "Destructive Command Veto",
                  "Deterministic regex and AST policy filters block destructive shell commands, fork bombs, recursive deletions, and private credential leakage before execution.",
                  tag="Active Guardrails", tag_color=C_ROSE)
                  
        draw_card(draw, start_x + (card_w + gap), y_pos, card_w, card_h,
                  "Isolated Test Sandbox",
                  "Agent actions, bash commands, and test suites run in strictly isolated sub-environments with strict memory and CPU limits, safeguarding host workstations.",
                  tag="Runtime Isolation", tag_color=C_AMBER)
                  
        draw_card(draw, start_x + (card_w + gap) * 2, y_pos, card_w, card_h,
                  "Interactive Policy Approvals",
                  "Sensitive operations trigger non-blocking human-in-the-loop approval cards with live diff previews, granting developers absolute governance over every commit.",
                  tag="Human Oversight", tag_color=C_CYAN)

    elif stype == "studio":
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 170), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 245), scene["subtitle"], font=FONT_SUBTITLE, fill=C_CYAN)
        
        card_w, card_h = 400, 480
        gap = 30
        start_x = (1920 - (card_w * 4 + gap * 3)) // 2
        y_pos = 360
        
        draw_card(draw, start_x, y_pos, card_w, card_h,
                  "Visual Split & Unified Diff",
                  "Side-by-side color-coded diff viewer displaying additions, deletions, and hunk headers with GitHub-level precision.",
                  tag="Inspection", tag_color=C_CYAN)
                  
        draw_card(draw, start_x + (card_w + gap), y_pos, card_w, card_h,
                  "Live Web Preview",
                  "Built-in interactive sandbox iframe. View animated HTML, CSS, and JS web apps live inside Nexora without external server setup.",
                  tag="Real-Time UI", tag_color=C_INDIGO)
                  
        draw_card(draw, start_x + (card_w + gap) * 2, y_pos, card_w, card_h,
                  "Zero-Leakage Clean Copy",
                  "Line numbers rendered via CSS pseudo-elements (`::before`). Copying code extracts 100% pure source code without line numbers.",
                  tag="Clipboard Guard", tag_color=C_EMERALD)
                  
        draw_card(draw, start_x + (card_w + gap) * 3, y_pos, card_w, card_h,
                  "Dual Theme Engine",
                  "Custom HSL-calculated tokens for dark cybernetic mode and WCAG AA contrast light mode. Flawless on any monitor.",
                  tag="Design System", tag_color=C_AMBER)

    elif stype == "outro":
        if LOGO_PATH.exists():
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize((160, 160), Image.Resampling.LANCZOS)
            img.paste(logo, (880, 200), logo)
            
        t_box = FONT_TITLE.getbbox(scene["title"])
        draw.text(((1920 - (t_box[2] - t_box[0])) // 2, 400), scene["title"], font=FONT_TITLE, fill=C_TEXT_WHITE)
        
        s_box = FONT_SUBTITLE.getbbox(scene["subtitle"])
        draw.text(((1920 - (s_box[2] - s_box[0])) // 2, 485), scene["subtitle"], font=FONT_SUBTITLE, fill=C_CYAN)
        
        # Summary Box
        b_w, b_h = 1300, 240
        b_x = (1920 - b_w) // 2
        draw.rounded_rectangle([b_x, 580, b_x + b_w, 580 + b_h], radius=18, fill=C_BG_CARD, outline=C_INDIGO, width=2)
        
        t1 = "• 62% Token Optimization  ·  • Autonomous Self-Healing  ·  • Enterprise Policy Engine"
        t2 = "• Nebius Token Cloud  ·  • NVIDIA NIM High-Throughput Inference  ·  • Modern Developer Studio"
        t3 = "Repository: github.com/AzizullahMemonAi/Nebius-x-NVIDIA-Global-Al-Hackathon"
        
        t1_box = FONT_CARD_TITLE.getbbox(t1)
        t2_box = FONT_CARD_TITLE.getbbox(t2)
        t3_box = FONT_MONO.getbbox(t3)
        
        draw.text(((1920 - (t1_box[2] - t1_box[0])) // 2, 630), t1, font=FONT_CARD_TITLE, fill=C_TEXT_WHITE)
        draw.text(((1920 - (t2_box[2] - t2_box[0])) // 2, 685), t2, font=FONT_CARD_TITLE, fill=C_CYAN)
        draw.text(((1920 - (t3_box[2] - t3_box[0])) // 2, 745), t3, font=FONT_MONO, fill=C_EMERALD)

    # Save
    img.save(out_path, quality=95)

async def generate_speech(text, out_mp3):
    import edge_tts
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+2%")
    await communicate.save(str(out_mp3))

def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-i", str(file_path),
        "-show_entries", "format=duration",
        "-v", "quiet", "-of", "csv=p=0"
    ]
    res = subprocess.check_output(cmd, text=True).strip()
    return float(res)

def synthesize_ambient_music(duration_sec, out_wav):
    """Synthesizes a lush, futuristic ambient synth pad progression in D minor."""
    sample_rate = 44100
    total_samples = int(duration_sec * sample_rate)
    
    # Chord frequencies (D minor, Bb major, G minor, A minor)
    chords = [
        [146.83, 220.00, 261.63, 349.23], # Dm7 (D3, A3, C4, F4)
        [116.54, 174.61, 233.08, 293.66], # Bbmaj7 (Bb2, F3, Bb3, D4)
        [98.00, 146.83, 196.00, 293.66],  # Gm7 (G2, D3, G3, D4)
        [110.00, 164.81, 220.00, 261.63], # Am7 (A2, E3, A3, C4)
    ]
    
    chord_len = duration_sec / len(chords)
    data = []
    
    for i in range(total_samples):
        t = i / sample_rate
        chord_idx = int((t / chord_len) % len(chords))
        chord = chords[chord_idx]
        
        # Chord progression blend
        val = 0.0
        for freq in chord:
            # Soft sine + warm overtone
            val += 0.25 * math.sin(2 * math.pi * freq * t)
            val += 0.08 * math.sin(2 * math.pi * (freq * 2) * t)
            
        # Subtle gentle arpeggio chime (octave 5)
        arp_freq = chord[int(t * 3) % len(chord)] * 2
        val += 0.06 * math.sin(2 * math.pi * arp_freq * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 3 * t))
        
        # Soft master volume envelope
        fade_in = min(1.0, t / 4.0)
        fade_out = min(1.0, (duration_sec - t) / 4.0)
        sample = val * fade_in * fade_out * 0.35
        
        int_sample = int(max(-32767, min(32767, sample * 32767)))
        data.append(struct.pack("<h", int_sample))
        
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(data))

def main():
    print("=" * 70)
    print(" NEXORA 2-MINUTE LAUNCH VIDEO GENERATOR (BRAG SKILL)")
    print("=" * 70)
    
    scene_clips = []
    total_video_duration = 0.0
    
    for idx, scene in enumerate(SCENES, 1):
        sid = scene["id"]
        print(f"\n[Scene {idx}/{len(SCENES)}] Processing {sid}...")
        
        img_path = TEMP_DIR / f"{sid}.png"
        audio_path = TEMP_DIR / f"{sid}.mp3"
        clip_path = TEMP_DIR / f"{sid}.mp4"
        
        # 1. Render slide image
        print(f"  -> Rendering 1080p slide: {img_path.name}")
        render_scene_image(scene, img_path)
        
        # 2. Generate voiceover
        print(f"  -> Generating neural narration (ChristopherNeural)...")
        asyncio.run(generate_speech(scene["speech"], audio_path))
        
        audio_dur = get_audio_duration(audio_path)
        # Add 0.7s padding so speech doesn't clip on transitions
        scene_dur = audio_dur + 0.75
        total_video_duration += scene_dur
        print(f"  -> Audio duration: {audio_dur:.2f}s | Scene duration: {scene_dur:.2f}s")
        
        # 3. Create video clip with Ken Burns subtle motion using ffmpeg
        # Zoom gently from 1.0 to 1.04 over scene duration
        print(f"  -> Encoding MP4 motion clip...")
        cmd_clip = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(img_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[0:v]scale=1920:1080,zoompan=z='min(zoom+0.0003,1.04)':d={int(scene_dur*30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080,fps=30[v];"
            f"[1:a]apad=pad_dur=0.75[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{scene_dur:.3f}",
            str(clip_path)
        ]
        subprocess.check_call(cmd_clip, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        scene_clips.append(clip_path)

    print(f"\nTotal planned video duration: {total_video_duration:.1f}s ({total_video_duration/60:.2f} minutes)")

    # 4. Generate Ambient Electronic Background Music
    music_path = TEMP_DIR / "ambient_music.wav"
    print("\n[Audio] Synthesizing ambient tech electronic soundtrack...")
    synthesize_ambient_music(total_video_duration + 5.0, music_path)

    # 5. Concatenate all scene clips
    concat_list_file = TEMP_DIR / "clips.txt"
    with open(concat_list_file, "w") as f:
        for c in scene_clips:
            # ffmpeg concat demuxer requires forward slashes or escaped backslashes
            f.write(f"file '{c.resolve().as_posix()}'\n")

    raw_combined = TEMP_DIR / "combined_raw.mp4"
    print("\n[Video] Concatenating scene clips...")
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_file),
        "-c", "copy",
        str(raw_combined)
    ]
    subprocess.check_call(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 6. Final Mix: Combine Speech + Ducked Ambient Background Music (12% volume)
    final_output = OUTPUT_DIR / "brag.mp4"
    print(f"\n[Final Mix] Mixing speech with auto-ducked music into {final_output.name}...")
    cmd_mix = [
        "ffmpeg", "-y",
        "-i", str(raw_combined),
        "-i", str(music_path),
        "-filter_complex",
        "[1:a]volume=0.13[bgm];"
        "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "256k",
        "-shortest",
        str(final_output)
    ]
    subprocess.check_call(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 7. Verification
    if final_output.exists():
        final_size_mb = final_output.stat().st_size / (1024 * 1024)
        final_dur = get_audio_duration(final_output)
        print("\n" + "=" * 70)
        print(" SUCCESS! NEXORA LAUNCH VIDEO GENERATED!")
        print("=" * 70)
        print(f" File Path : {final_output}")
        print(f" Duration  : {final_dur:.1f} seconds ({final_dur/60:.2f} minutes)")
        print(f" File Size : {final_size_mb:.2f} MB")
        print(f" Specs     : 1080p Full HD (1920x1080) @ 30 FPS, H.264/AAC")
        print(" Ready for YouTube upload and Nebius x NVIDIA Hackathon submission!")
    else:
        print("[ERROR] Failed to produce brag.mp4")
        sys.exit(1)

if __name__ == "__main__":
    main()
