#!/usr/bin/env python3
"""
Web Exporter v1.0
=================
Runs the full CBB analysis pipeline and generates a self-contained
static HTML page deployable on GitHub Pages.

Output:
    docs/index.html  — complete static page (all data embedded)

GitHub Pages setup:
    1. Push your repo to GitHub
    2. Settings → Pages → Source: Deploy from branch
    3. Branch: main (or master), Folder: /docs
    4. Your page will be at: https://<username>.github.io/<repo>/

Run after every update to re-generate the page:
    python web_exporter.py
    python web_exporter.py --sims 5000   # faster run
    python web_exporter.py --out docs/index.html

Author: Jordan's Custom System
Date:   March 2026
"""

import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betting_analyzer import run_analysis

# Pool recommendation data (from optimizer runs)
POOL_DATA = {
    "espn_74": {
        "name":      "ESPN / CBS Bracket Pool (74 entries)",
        "scoring":   "ESPN Standard: 10/20/40/80/160/320",
        "entries":   [
            {
                "label":     "Entry #1 — Walters (Highest Win%)",
                "champion":  "Arizona",
                "final_four": ["Houston", "Arizona", "Iowa State", "UConn"],
                "win_pct":   8.3,
                "top3_pct":  19.4,
                "avg_score": 845.6,
            },
            {
                "label":     "Entry #2 — Feustel (Best EV)",
                "champion":  "Florida",
                "final_four": ["Florida", "Iowa State", "Houston", "Virginia"],
                "win_pct":   8.8,
                "top3_pct":  12.6,
                "avg_score": 761.1,
            },
            {
                "label":     "Entry #3 — Boston (Top-3 Ceiling)",
                "champion":  "Florida",
                "final_four": ["Duke", "Purdue", "Florida", "Michigan"],
                "win_pct":   10.7,
                "top3_pct":  13.5,
                "avg_score": 714.4,
            },
        ],
        "chalk": {
            "champion":    "Michigan",
            "final_four":  ["Duke", "Michigan", "Houston", "Arizona"],
            "win_pct":     0.0,
            "avg_score":   975.1,
            "note":        "Chalk never wins a 74-person pool",
        },
        "tiebreaker": {"value": 154, "range": "150–158"},
    },
    "seed_bonus_35": {
        "name":    "Seed-Bonus Pool (35 entries)",
        "scoring": "Points + Winning Seed: R1=1+seed, R2=2+seed, S16=4+seed...",
        "entries": [
            {
                "label":      "Entry #1 — Boston (Top-3 Ceiling)",
                "champion":   "Arizona",
                "final_four": ["Houston", "Arizona", "Iowa State", "Duke"],
                "win_pct":    7.2,
                "top3_pct":   15.3,
                "avg_score":  228.6,
            },
            {
                "label":      "Entry #2 — Walters (Highest Win%)",
                "champion":   "Arizona",
                "final_four": ["Illinois", "Arizona", "Kansas", "Iowa State"],
                "win_pct":    7.6,
                "top3_pct":   14.2,
                "avg_score":  216.9,
            },
            {
                "label":      "Entry #3 — Feustel (Best EV)",
                "champion":   "Duke",
                "final_four": ["Duke", "Michigan", "Purdue", "Florida"],
                "win_pct":    5.9,
                "top3_pct":   12.6,
                "avg_score":  233.5,
            },
        ],
        "chalk": {
            "champion":   "Michigan",
            "final_four": ["Duke", "Michigan", "Houston", "Arizona"],
            "win_pct":    0.4,
            "avg_score":  249.2,
            "note":       "Chalk ceiling ~315 pts — winners typically reach 355+",
        },
        "key_insight": "2022 winner scored 370 pts with only 26 correct picks (14.2 pts/pick). One deep upset run beats near-perfect chalk.",
    },
    "ten_team_25": {
        "name":    "Dave Kerr 10-Team Pool (25 entries)",
        "scoring": "Wins × Seed + $10 bonus reach Championship + $10 win Championship",
        "deadline": "dave.kerr5@gmail.com — before March 19 tip-off",
        "fee":     "$20/entry, up to 5 entries",
        "recommended": ["Michigan", "Duke", "Houston", "Kansas", "Wisconsin",
                        "Vanderbilt", "Texas Tech", "Louisville", "North Carolina", "Kentucky"],
        "strategy":    "BALANCED",
        "mean_score":  79.3,
        "p90_score":   112.0,
        "floor_score": 62.0,
        "alternatives": [
            {"strategy": "EV_MAX",     "mean": 79.2, "p90": 110.0, "max": 203},
            {"strategy": "UPSIDE",     "mean": 67.4, "p90":  97.0, "max": 186},
            {"strategy": "SAFE",       "mean": 78.2, "p90": 107.0, "max": 213},
            {"strategy": "CINDERELLA", "mean": 76.2, "p90": 103.0, "max": 188},
        ],
    },
}


def build_html(data: dict) -> str:
    """Build the complete HTML page with all data embedded."""

    # Pre-process data for template
    futures_strong = [f for f in data["futures"]
                      if f["edge_pp"] and f["edge_pp"] >= 5]
    futures_value  = [f for f in data["futures"]
                      if f["edge_pp"] and 2 <= f["edge_pp"] < 5]
    upset_top      = data["upset_edges"][:5]
    top_props      = data["advancement_props"][:8]
    spreads_r64    = data["spreads"]
    ou_games       = data["over_unders"][:8]
    champ_ou       = data["championship_ou"]
    injuries       = data["meta"]["injuries"]
    generated      = datetime.now().strftime("%B %d, %Y at %I:%M %p ET")

    # JSON blobs for JS
    spreads_json   = json.dumps(spreads_r64)
    props_json     = json.dumps(data["advancement_props"][:25])
    futures_json   = json.dumps(data["futures"][:12])
    champ_probs_json = json.dumps(
        sorted(data["sim_results"]["champion_prob"].items(),
               key=lambda x: -x[1])[:10]
    )

    def badge(text, color):
        colors = {
            "gold":   "background:#f0b429;color:#1a1a2e",
            "blue":   "background:#38bdf8;color:#0a0f1e",
            "green":  "background:#22c55e;color:#0a0f1e",
            "red":    "background:#ef4444;color:#fff",
            "gray":   "background:#374151;color:#9ca3af",
            "purple": "background:#a78bfa;color:#1a1a2e",
        }
        style = colors.get(color, colors["gray"])
        return f'<span class="badge" style="{style}">{text}</span>'

    def grade_color(grade):
        if "STRONG" in grade:  return "green"
        if "GOOD"   in grade:  return "blue"
        if "LEAN"   in grade:  return "gold"
        return "gray"

    # Build futures rows
    futures_rows = ""
    for f in data["futures"][:12]:
        if f["edge_pp"] is None:
            edge_html = '<span class="dim">N/A</span>'
            grade_html = ""
        else:
            color = grade_color(f["grade"])
            edge_sign = "+" if f["edge_pp"] >= 0 else ""
            edge_html = f'<span class="{"value-pos" if f["edge_pp"] > 0 else "value-neg"}">{edge_sign}{f["edge_pp"]}pp</span>'
            grade_html = badge(f["grade"].strip(), color)

        futures_rows += f"""
        <tr>
          <td class="team-name">{f['team']}</td>
          <td class="mono">{f['model_pct']}%</td>
          <td class="mono highlight">{f['model_odds']}</td>
          <td class="mono">{f['market_odds']}</td>
          <td>{edge_html}</td>
          <td>{grade_html}</td>
        </tr>"""

    # Build upset edge rows
    upset_rows = ""
    for u in upset_top:
        upset_rows += f"""
        <tr>
          <td>({u['seed_dog']}) <span class="team-name">{u['underdog']}</span></td>
          <td class="dim">vs ({u['seed_fav']}) {u['favorite']}</td>
          <td class="mono">{u['region']}</td>
          <td class="mono">{u['model_upset']}%</td>
          <td class="mono dim">{u['hist_upset']}%</td>
          <td class="value-pos mono">+{u['edge_pp']}pp</td>
          <td class="mono highlight">{u['dog_ml']}</td>
        </tr>"""

    # Build O/U rows
    ou_rows = ""
    for g in ou_games:
        pace_color = "blue" if g["pace_note"] == "FAST" else "red" if g["pace_note"] == "SLOW" else "gray"
        ou_rows += f"""
        <tr>
          <td class="team-name">({g['seed1']}) {g['team1']}</td>
          <td class="dim">vs ({g['seed2']}) {g['team2']}</td>
          <td class="mono">{g['region']}</td>
          <td class="mono highlight">{g['rec_total']}</td>
          <td class="mono dim">{g['low_o_u']} – {g['high_o_u']}</td>
          <td>{badge(g['pace_note'], pace_color)}</td>
        </tr>"""

    # Build spread rows (R64)
    spread_rows = ""
    for s in spreads_r64:
        inj_fav = f" ⚕" if s["injuries_fav"] else ""
        inj_dog = f" ⚕" if s["injuries_dog"] else ""
        spread_rows += f"""
        <tr>
          <td class="team-name">({s['seed_fav']}) {s['favorite']}{inj_fav}</td>
          <td class="dim">vs ({s['seed_dog']}) {s['underdog']}{inj_dog}</td>
          <td class="mono">{s['region']}</td>
          <td class="mono highlight">{s['spread']:+.1f}</td>
          <td class="mono">{s['fav_ml']}</td>
          <td class="mono">{s['dog_ml']}</td>
          <td class="mono dim">{s['fav_win_prob']}% / {s['upset_prob']}%</td>
        </tr>"""

    # Build pool entries (ESPN)
    espn = POOL_DATA["espn_74"]
    espn_entries = ""
    for e in espn["entries"]:
        color = "green" if e["win_pct"] >= 10 else "blue" if e["win_pct"] >= 8 else "gold"
        espn_entries += f"""
        <div class="pool-entry">
          <div class="entry-label">{e['label']}</div>
          <div class="entry-champion">🏆 Champion: <strong>{e['champion']}</strong></div>
          <div class="entry-ff">Final Four: {' · '.join(e['final_four'])}</div>
          <div class="entry-stats">
            {badge(f"Win {e['win_pct']}%", color)}
            {badge(f"Top-3 {e['top3_pct']}%", "gray")}
            {badge(f"Avg {e['avg_score']:.0f} pts", "gray")}
          </div>
        </div>"""

    # 10-team pool
    ten = POOL_DATA["ten_team_25"]
    ten_teams_html = "".join(
        f'<div class="team-pill">{i+1}. {t}</div>'
        for i, t in enumerate(ten["recommended"])
    )
    ten_alts = "".join(
        f'<tr><td>{a["strategy"]}</td><td class="mono">{a["mean"]:.1f}</td>'
        f'<td class="mono">{a["p90"]:.1f}</td><td class="mono">{a["max"]}</td></tr>'
        for a in ten["alternatives"]
    )

    # Seed bonus pool
    sb = POOL_DATA["seed_bonus_35"]
    sb_entries = ""
    for e in sb["entries"]:
        color = "green" if e["win_pct"] >= 7.5 else "blue" if e["win_pct"] >= 7 else "gold"
        sb_entries += f"""
        <div class="pool-entry">
          <div class="entry-label">{e['label']}</div>
          <div class="entry-champion">🏆 Champion: <strong>{e['champion']}</strong></div>
          <div class="entry-ff">Final Four: {' · '.join(e['final_four'])}</div>
          <div class="entry-stats">
            {badge(f"Win {e['win_pct']}%", color)}
            {badge(f"Top-3 {e['top3_pct']}%", "gray")}
            {badge(f"Avg {e['avg_score']:.0f} pts", "gray")}
          </div>
        </div>"""

    # Injury list
    injury_html = "".join(
        f'<div class="injury-item">⚕ {inj}</div>' for inj in injuries
    )

    champ_pred   = data["champion_prediction"]
    champ_pct    = data["champion_pct"]
    ff_teams     = " · ".join(f["team"] for f in data["final_four"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 March Madness Analytics — 13_Spades</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:       #080b14;
    --surface:  #0f1628;
    --surface2: #161f38;
    --border:   #1e2d52;
    --gold:     #f0b429;
    --gold-dim: #7a5c14;
    --blue:     #38bdf8;
    --blue-dim: #1e4a6e;
    --green:    #22c55e;
    --red:      #ef4444;
    --purple:   #a78bfa;
    --text:     #e2e8f0;
    --dim:      #64748b;
    --font-head: 'Barlow Condensed', sans-serif;
    --font-mono: 'IBM Plex Mono', monospace;
    --font-body: 'Barlow', sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 15px;
    line-height: 1.5;
    overflow-x: hidden;
  }}

  /* ─── HEADER ─────────────────────────────────────────── */
  header {{
    background: linear-gradient(135deg, #0a0f20 0%, #0f1a35 50%, #0a1528 100%);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(8px);
  }}
  .header-inner {{
    max-width: 1400px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 32px;
    height: 64px;
  }}
  .logo {{
    font-family: var(--font-head);
    font-weight: 900;
    font-size: 22px;
    letter-spacing: 2px;
    color: var(--gold);
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .logo span {{ color: var(--text); }}

  nav {{ display: flex; gap: 4px; }}
  nav button {{
    background: none;
    border: none;
    color: var(--dim);
    font-family: var(--font-head);
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 8px 16px;
    cursor: pointer;
    border-radius: 4px;
    transition: all 0.2s;
    position: relative;
  }}
  nav button:hover {{ color: var(--text); background: var(--surface2); }}
  nav button.active {{
    color: var(--gold);
    background: rgba(240,180,41,0.08);
  }}
  nav button.active::after {{
    content: '';
    position: absolute;
    bottom: -1px;
    left: 16px;
    right: 16px;
    height: 2px;
    background: var(--gold);
  }}

  .header-meta {{
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--dim);
    text-align: right;
  }}
  .header-meta strong {{ color: var(--green); }}

  /* ─── HERO ────────────────────────────────────────────── */
  .hero {{
    background: linear-gradient(180deg, #0f1a35 0%, var(--bg) 100%);
    padding: 48px 24px 40px;
    border-bottom: 1px solid var(--border);
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: 'MARCH MADNESS 2026';
    position: absolute;
    top: -10px;
    right: -20px;
    font-family: var(--font-head);
    font-weight: 900;
    font-size: 140px;
    color: rgba(240,180,41,0.03);
    letter-spacing: -4px;
    pointer-events: none;
    white-space: nowrap;
  }}
  .hero-inner {{
    max-width: 1400px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 24px;
  }}
  .hero-stat {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
  }}
  .hero-stat::after {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--gold);
  }}
  .hero-stat.blue::after  {{ background: var(--blue); }}
  .hero-stat.green::after {{ background: var(--green); }}
  .hero-stat.purple::after {{ background: var(--purple); }}

  .stat-label {{
    font-family: var(--font-head);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--dim);
    margin-bottom: 8px;
  }}
  .stat-value {{
    font-family: var(--font-head);
    font-weight: 900;
    font-size: 38px;
    line-height: 1;
    color: var(--gold);
    margin-bottom: 4px;
  }}
  .hero-stat.blue  .stat-value  {{ color: var(--blue); }}
  .hero-stat.green .stat-value  {{ color: var(--green); }}
  .hero-stat.purple .stat-value {{ color: var(--purple); }}
  .stat-sub {{
    font-size: 13px;
    color: var(--dim);
  }}

  /* ─── MAIN LAYOUT ────────────────────────────────────── */
  main {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 32px 24px;
  }}

  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  /* ─── SECTION HEADERS ────────────────────────────────── */
  .section-header {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }}
  .section-title {{
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 22px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--text);
  }}
  .section-sub {{
    font-size: 13px;
    color: var(--dim);
  }}

  /* ─── CARDS ──────────────────────────────────────────── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 20px;
  }}
  .card-title {{
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 16px;
  }}

  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}

  /* ─── TABLES ─────────────────────────────────────────── */
  .table-wrap {{ overflow-x: auto; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  thead tr {{
    border-bottom: 1px solid var(--border);
  }}
  th {{
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--dim);
    padding: 8px 12px;
    text-align: left;
    white-space: nowrap;
  }}
  td {{
    padding: 10px 12px;
    border-bottom: 1px solid rgba(30,45,82,0.5);
    vertical-align: middle;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: var(--surface2); }}
  .team-name  {{ font-weight: 600; color: var(--text); }}
  .mono       {{ font-family: var(--font-mono); font-size: 12px; }}
  .highlight  {{ color: var(--gold); font-weight: 600; }}
  .dim        {{ color: var(--dim); }}
  .value-pos  {{ color: var(--green); font-family: var(--font-mono); font-size: 12px; font-weight: 600; }}
  .value-neg  {{ color: var(--red);   font-family: var(--font-mono); font-size: 12px; }}

  /* ─── BADGES ─────────────────────────────────────────── */
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    white-space: nowrap;
  }}

  /* ─── INJURY BAR ─────────────────────────────────────── */
  .injury-bar {{
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.2);
    border-left: 3px solid var(--red);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 24px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }}
  .injury-label {{
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--red);
    margin-right: 4px;
  }}
  .injury-item {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: #f87171;
    background: rgba(239,68,68,0.1);
    padding: 2px 8px;
    border-radius: 3px;
  }}

  /* ─── POOL ENTRIES ───────────────────────────────────── */
  .pool-entry {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 18px;
    margin-bottom: 12px;
  }}
  .entry-label {{
    font-family: var(--font-head);
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.5px;
    color: var(--gold);
    margin-bottom: 6px;
  }}
  .entry-champion {{
    font-size: 15px;
    margin-bottom: 4px;
  }}
  .entry-ff {{
    font-size: 12px;
    color: var(--dim);
    font-family: var(--font-mono);
    margin-bottom: 10px;
  }}
  .entry-stats {{ display: flex; gap: 6px; flex-wrap: wrap; }}

  /* ─── 10-TEAM GRID ───────────────────────────────────── */
  .team-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
    margin: 16px 0;
  }}
  .team-pill {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    text-align: center;
  }}
  .team-pill:nth-child(-n+2) {{
    border-color: var(--gold-dim);
    color: var(--gold);
  }}

  /* ─── CHART BAR ──────────────────────────────────────── */
  .bar-chart {{ display: flex; flex-direction: column; gap: 8px; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; }}
  .bar-label {{
    font-size: 12px;
    width: 130px;
    flex-shrink: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .bar-track {{
    flex: 1;
    height: 20px;
    background: var(--surface2);
    border-radius: 3px;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    background: var(--gold);
    border-radius: 3px;
    display: flex;
    align-items: center;
    padding-left: 6px;
    transition: width 1s ease;
  }}
  .bar-fill.blue {{ background: var(--blue); }}
  .bar-pct {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--bg);
    font-weight: 600;
  }}
  .bar-pct-right {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--dim);
    width: 48px;
    text-align: right;
    flex-shrink: 0;
  }}

  /* ─── INSIGHT BOX ────────────────────────────────────── */
  .insight {{
    background: rgba(240,180,41,0.06);
    border: 1px solid rgba(240,180,41,0.2);
    border-left: 3px solid var(--gold);
    border-radius: 6px;
    padding: 14px 16px;
    margin: 16px 0;
    font-size: 13px;
    line-height: 1.6;
    color: #cbd5e1;
  }}
  .insight strong {{ color: var(--gold); }}

  /* ─── OU DISPLAY ─────────────────────────────────────── */
  .ou-big {{
    font-family: var(--font-head);
    font-weight: 900;
    font-size: 56px;
    color: var(--gold);
    line-height: 1;
  }}

  /* ─── FOOTER ─────────────────────────────────────────── */
  footer {{
    border-top: 1px solid var(--border);
    padding: 20px 24px;
    text-align: center;
    font-size: 11px;
    color: var(--dim);
    font-family: var(--font-mono);
    margin-top: 40px;
  }}

  /* ─── RESPONSIVE ─────────────────────────────────────── */
  @media (max-width: 900px) {{
    .hero-inner {{ grid-template-columns: 1fr 1fr; }}
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
    .team-grid {{ grid-template-columns: repeat(2, 1fr); }}
    nav button {{ padding: 8px 10px; font-size: 11px; }}
  }}
  @media (max-width: 600px) {{
    .hero-inner {{ grid-template-columns: 1fr; }}
    .logo {{ font-size: 16px; }}
    .stat-value {{ font-size: 28px; }}
  }}
</style>
</head>
<body>

<!-- HEADER -->
<header>
  <div class="header-inner">
    <div class="logo">13_Spades <span>/ MM26</span></div>
    <nav id="nav">
      <button class="active" onclick="switchTab('bracket')">Bracket</button>
      <button onclick="switchTab('betting')">Betting</button>
      <button onclick="switchTab('pools')">Pools</button>
      <button onclick="switchTab('spreads')">Spreads</button>
      <button onclick="switchTab('props')">Props</button>
    </nav>
    <div class="header-meta">
      Generated <strong>{generated}</strong><br>
      {data['meta']['model']}
    </div>
  </div>
</header>

<!-- HERO -->
<div class="hero">
  <div class="hero-inner">
    <div class="hero-stat">
      <div class="stat-label">Model Champion</div>
      <div class="stat-value">{champ_pred.split()[0].upper()}</div>
      <div class="stat-sub">{champ_pred} — {champ_pct}% probability</div>
    </div>
    <div class="hero-stat blue">
      <div class="stat-label">Predicted Final Four</div>
      <div class="stat-value" style="font-size:22px;padding-top:6px">{ff_teams}</div>
      <div class="stat-sub">Top 4 by Final Four probability</div>
    </div>
    <div class="hero-stat green">
      <div class="stat-label">Top Upset Edge</div>
      <div class="stat-value" style="font-size:28px;padding-top:4px">
        {upset_top[0]['underdog'] if upset_top else 'N/A'}
      </div>
      <div class="stat-sub">
        {f"+{upset_top[0]['edge_pp']}pp above historical base rate" if upset_top else ""}
      </div>
    </div>
    <div class="hero-stat purple">
      <div class="stat-label">Championship O/U</div>
      <div class="stat-value">{champ_ou['rec_total']}</div>
      <div class="stat-sub">Range: {champ_ou['range']} · Both top-3 defenses</div>
    </div>
  </div>
</div>

<main>

<!-- INJURY BAR -->
<div class="injury-bar">
  <span class="injury-label">⚕ Active Injuries</span>
  {injury_html}
</div>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TAB: BRACKET                                        -->
<!-- ═══════════════════════════════════════════════════ -->
<div id="tab-bracket" class="tab-content active">

  <div class="section-header">
    <span class="section-title">Tournament Predictions</span>
    <span class="section-sub">Monte Carlo — {data['meta']['n_sims']:,} simulations · Boston/Walters/Feustel composite</span>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">Championship Probabilities</div>
      <div class="bar-chart" id="champ-chart"></div>
    </div>

    <div class="card">
      <div class="card-title">Final Four Probabilities</div>
      <div class="bar-chart" id="ff-chart"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Elite 8 Advancement Probabilities</div>
    <div class="bar-chart" id="e8-chart"></div>
  </div>

  <div class="card">
    <div class="card-title">Championship Game Analysis</div>
    <div style="display:flex;align-items:center;gap:32px;flex-wrap:wrap">
      <div>
        <div style="font-size:13px;color:var(--dim);margin-bottom:4px">Projected Total</div>
        <div class="ou-big">{champ_ou['rec_total']}</div>
        <div style="font-size:13px;color:var(--dim);margin-top:4px">Range: {champ_ou['range']}</div>
      </div>
      <div style="flex:1;min-width:280px">
        <div class="insight">
          <strong>Methodology:</strong> {champ_ou['basis']}<br><br>
          <strong>Note:</strong> {champ_ou['note']}
        </div>
      </div>
    </div>
  </div>

</div>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TAB: BETTING                                        -->
<!-- ═══════════════════════════════════════════════════ -->
<div id="tab-betting" class="tab-content">

  <div class="section-header">
    <span class="section-title">Betting Analysis</span>
    <span class="section-sub">Model edge vs market implied odds — not financial advice</span>
  </div>

  <div class="grid-2">

    <div class="card">
      <div class="card-title">Championship Futures — Model vs Market</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Team</th><th>Model%</th><th>Model Odds</th>
              <th>Market</th><th>Edge</th><th>Grade</th>
            </tr>
          </thead>
          <tbody>{futures_rows}</tbody>
        </table>
      </div>
      <div class="insight" style="margin-top:12px;font-size:12px">
        <strong>Note:</strong> Market odds are pre-tournament estimates.
        Update with live lines for precise edge calculation.
        Only bet where edge ≥ 5pp and Kelly sizing suggests ≥ 1% bankroll.
      </div>
    </div>

    <div>
      <div class="card">
        <div class="card-title">Top Upset Edges — R64</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Underdog</th><th>Opponent</th><th>Region</th>
                <th>Model%</th><th>Hist%</th><th>Edge</th><th>Dog ML</th>
              </tr>
            </thead>
            <tbody>{upset_rows}</tbody>
          </table>
        </div>
        <div class="insight" style="margin-top:12px;font-size:12px">
          <strong>Edge</strong> = model upset probability minus historical seed-line base rate.
          Positive edge means model sees more upset potential than the historical average.
        </div>
      </div>

      <div class="card">
        <div class="card-title">Key Game Over/Unders</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Team 1</th><th>Team 2</th><th>Region</th><th>Model O/U</th><th>Range</th><th>Pace</th></tr>
            </thead>
            <tbody>{ou_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

  </div>

</div>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TAB: POOLS                                          -->
<!-- ═══════════════════════════════════════════════════ -->
<div id="tab-pools" class="tab-content">

  <div class="section-header">
    <span class="section-title">Pool Recommendations</span>
    <span class="section-sub">Optimized entries for each contest format</span>
  </div>

  <!-- ESPN 74-person -->
  <div class="card">
    <div class="card-title">{espn['name']}</div>
    <div style="font-size:12px;color:var(--dim);margin-bottom:16px">{espn['scoring']}</div>
    {espn_entries}
    <div class="insight" style="margin-top:8px">
      <strong>Tiebreaker (CBS):</strong> Submit <strong>{espn['tiebreaker']['value']} pts</strong>
      — range {espn['tiebreaker']['range']}. Both defenses top-3 nationally; expect a grind.
    </div>
  </div>

  <!-- Seed Bonus 35-person -->
  <div class="card">
    <div class="card-title">{sb['name']}</div>
    <div style="font-size:12px;color:var(--dim);margin-bottom:16px">{sb['scoring']}</div>
    {sb_entries}
    <div class="insight" style="margin-top:8px">
      <strong>2022 Blueprint:</strong> {sb['key_insight']}
    </div>
  </div>

  <!-- 10-team pool -->
  <div class="card">
    <div class="card-title">{ten['name']}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      <span style="font-size:12px;color:var(--dim)">{ten['scoring']}</span>
      <span class="badge" style="background:rgba(240,180,41,0.1);color:var(--gold)">{ten['deadline']}</span>
      <span class="badge" style="background:rgba(56,189,248,0.1);color:var(--blue)">{ten['fee']}</span>
    </div>
    <div style="font-family:var(--font-head);font-size:12px;letter-spacing:1px;color:var(--dim);text-transform:uppercase;margin-bottom:8px">
      Recommended: {ten['strategy']} Strategy
    </div>
    <div class="team-grid">{ten_teams_html}</div>
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin:16px 0">
      <div>
        <div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px">Mean Score</div>
        <div style="font-family:var(--font-head);font-weight:900;font-size:28px;color:var(--gold)">{ten['mean_score']}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px">P90 Ceiling</div>
        <div style="font-family:var(--font-head);font-weight:900;font-size:28px;color:var(--blue)">{ten['p90_score']}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px">P25 Floor</div>
        <div style="font-family:var(--font-head);font-weight:900;font-size:28px;color:var(--purple)">{ten['floor_score']}</div>
      </div>
    </div>
    <div style="font-family:var(--font-head);font-size:12px;letter-spacing:1px;color:var(--dim);text-transform:uppercase;margin-bottom:8px">Alternative Strategies</div>
    <div class="table-wrap">
      <table style="font-size:12px">
        <thead><tr><th>Strategy</th><th>Mean</th><th>P90</th><th>Max</th></tr></thead>
        <tbody>{ten_alts}</tbody>
      </table>
    </div>
  </div>

</div>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TAB: SPREADS                                        -->
<!-- ═══════════════════════════════════════════════════ -->
<div id="tab-spreads" class="tab-content">

  <div class="section-header">
    <span class="section-title">R64 Spread Lines</span>
    <span class="section-sub">Walters model — neutral site, injury-adjusted · ⚕ = injured player</span>
  </div>

  <div class="card">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Favorite</th><th>Underdog</th><th>Region</th>
            <th>Spread</th><th>Fav ML</th><th>Dog ML</th><th>Win Prob</th>
          </tr>
        </thead>
        <tbody>{spread_rows}</tbody>
      </table>
    </div>
  </div>

</div>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TAB: PROPS                                          -->
<!-- ═══════════════════════════════════════════════════ -->
<div id="tab-props" class="tab-content">

  <div class="section-header">
    <span class="section-title">Round Advancement Props</span>
    <span class="section-sub">Model-implied American odds for each round</span>
  </div>

  <div class="card">
    <div class="table-wrap">
      <table id="props-table">
        <thead>
          <tr>
            <th>Team</th><th>Seed</th><th>Region</th><th>Profile</th>
            <th>R32</th><th>S16</th><th>E8</th><th>FF</th><th>Champ</th>
            <th>R32 Odds</th><th>S16 Odds</th><th>FF Odds</th><th>Champ Odds</th>
          </tr>
        </thead>
        <tbody id="props-body"></tbody>
      </table>
    </div>
  </div>

</div>

</main>

<footer>
  2026 NCAA Tournament Analysis · Boston/Walters/Feustel Composite Model v2.4 ·
  {data['meta']['n_sims']:,} Monte Carlo simulations ·
  Generated {generated} ·
  13_Spades
</footer>

<script>
// ── Data ──────────────────────────────────────────────────────────────────────
const CHAMP_PROBS = {champ_probs_json};
const PROPS_DATA  = {props_json};
const FUTURES     = {futures_json};
const SPREADS     = {spreads_json};

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelectorAll('nav button').forEach(b => {{
    if (b.textContent.toLowerCase().includes(name.substring(0, 4))) b.classList.add('active');
  }});
  if (name === 'bracket') renderCharts();
  if (name === 'props')   renderPropsTable();
}}

// ── Bar chart renderer ────────────────────────────────────────────────────────
function renderBarChart(containerId, data, maxVal, color) {{
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = data.map(([name, val]) => {{
    const pct = ((val / maxVal) * 100).toFixed(0);
    const display = typeof val === 'number' ? val.toFixed(1) + '%' : val;
    return `<div class="bar-row">
      <div class="bar-label">${{name}}</div>
      <div class="bar-track">
        <div class="bar-fill ${{color}}" style="width:${{pct}}%">
          <span class="bar-pct">${{display}}</span>
        </div>
      </div>
      <div class="bar-pct-right">${{display}}</div>
    </div>`;
  }}).join('');
}}

function renderCharts() {{
  const champData = CHAMP_PROBS.slice(0, 10);
  const maxChamp  = champData.length ? champData[0][1] : 1;
  renderBarChart('champ-chart', champData, maxChamp, '');

  // Final Four from props
  const ffData = PROPS_DATA
    .filter(t => t.ff_pct > 0)
    .sort((a, b) => b.ff_pct - a.ff_pct)
    .slice(0, 10)
    .map(t => [t.team, t.ff_pct]);
  const maxFF = ffData.length ? ffData[0][1] : 1;
  renderBarChart('ff-chart', ffData, maxFF, 'blue');

  // E8
  const e8Data = PROPS_DATA
    .filter(t => t.e8_pct > 0)
    .sort((a, b) => b.e8_pct - a.e8_pct)
    .slice(0, 12)
    .map(t => [t.team, t.e8_pct]);
  const maxE8 = e8Data.length ? e8Data[0][1] : 1;
  renderBarChart('e8-chart', e8Data, maxE8, 'blue');
}}

// ── Props table renderer ──────────────────────────────────────────────────────
function renderPropsTable() {{
  const tbody = document.getElementById('props-body');
  if (!tbody) return;
  tbody.innerHTML = PROPS_DATA.map(t => {{
    const inj = t.injuries.length ? ' <span style="color:var(--red)">⚕</span>' : '';
    const prof = `${{t.profile}}/8`;
    const profColor = t.profile >= 7 ? 'var(--green)' : t.profile >= 5 ? 'var(--gold)' : 'var(--dim)';
    return `<tr>
      <td class="team-name">${{t.team}}${{inj}}</td>
      <td class="mono dim">${{t.seed}}</td>
      <td class="dim">${{t.region}}</td>
      <td class="mono" style="color:${{profColor}}">${{prof}}</td>
      <td class="mono">${{t.r32_pct}}%</td>
      <td class="mono">${{t.s16_pct}}%</td>
      <td class="mono">${{t.e8_pct}}%</td>
      <td class="mono">${{t.ff_pct}}%</td>
      <td class="mono highlight">${{t.champion}}%</td>
      <td class="mono dim">${{t.r32_odds}}</td>
      <td class="mono dim">${{t.s16_odds}}</td>
      <td class="mono dim">${{t.ff_odds}}</td>
      <td class="mono highlight">${{t.champ_odds}}</td>
    </tr>`;
  }}).join('');
}}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  renderCharts();
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Web Exporter v1.0")
    parser.add_argument("--sims", type=int, default=10000)
    parser.add_argument("--out",  default="docs/index.html")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    print(f"Running analysis ({args.sims:,} sims)...")
    data = run_analysis(n_sims=args.sims)

    print("Generating HTML...")
    html = build_html(data)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(args.out) / 1024
    print(f"\n✓ Generated: {args.out}  ({size_kb:.0f} KB)")
    print(f"  Champion:   {data['champion_prediction']} ({data['champion_pct']}%)")
    print(f"  Upsets:     {len(data['upset_edges'])} edges found")
    print(f"  Futures:    {len(data['futures'])} teams evaluated")
    print(f"\nTo deploy: commit docs/index.html to GitHub → GitHub Pages serves it automatically")


if __name__ == "__main__":
    main()
