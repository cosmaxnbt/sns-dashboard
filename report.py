# -*- coding: utf-8 -*-
"""
분기 SNS 리포트 생성기
─────────────────────
대시보드와 동일한 웹 게시 CSV(daily_channel / posts / contents / analysis)를 읽어
분기 리포트 HTML을 reports/<YYYY-Qn>.html 로 생성하고 reports/index.json 을 갱신한다.
GitHub Pages(sns-dashboard 저장소)에서 그대로 호스팅된다.

사용:  python report.py                # 직전 분기
       python report.py --quarter 2026-Q3
       python report.py --local ./csv  # 로컬 CSV 폴더로 테스트
"""
import os, re, csv, io, json, sys, argparse, datetime as dt
from collections import defaultdict

PUB = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSiWLnI2YpiicVbgQJWCi9ZU1iXhXnyFkcErrZKf_7BqZup6SRM7OHcjbBsxTfQOtkb09pLxq7aTsxS/pub"
CSV = {
    "daily":    f"{PUB}?gid=35459965&single=true&output=csv",
    "posts":    f"{PUB}?gid=1195479591&single=true&output=csv",
    "contents": f"{PUB}?gid=1938990605&single=true&output=csv",
    "analysis": f"{PUB}?gid=853775269&single=true&output=csv",
}
DASHBOARD_URL = "https://cosmaxnbt.github.io/sns-dashboard/"
CH = {
    "youtube":   {"name": "유튜브",     "color": "#E5343A"},
    "instagram": {"name": "인스타그램", "color": "#C13584"},
    "tiktok":    {"name": "틱톡",       "color": "#0097A7"},
}
CH_KEYS = ["youtube", "instagram", "tiktok"]
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)

# ── 유틸 ──────────────────────────────────────────────
def to_int(v):
    try:
        return int(float(str(v or "").replace(",", "")))
    except Exception:
        return 0

def fmt(n):
    n = to_int(n)
    return f"{n/10000:.1f}만" if n >= 10000 else f"{n:,}"

def pct(cur, prev):
    return None if not prev else round((cur - prev) / prev * 100, 1)

def arrow(p):
    if p is None:
        return '<span class="muted">–</span>'
    cls = "up" if p >= 0 else "down"
    return f'<span class="{cls}">{"▲" if p >= 0 else "▼"} {abs(p)}%</span>'

def norm_date(s):
    s = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""

def norm_ts(s):
    s = str(s or "").strip()
    d = norm_date(s)
    if d:
        return d
    m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", s)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""

def first_line(t):
    lines = [x.strip() for x in str(t or "").split("\n") if x.strip()]
    def meaningful(s):
        core = re.sub(r"#\S+", " ", s)
        core = re.sub(r"[\u200B-\u200D\uFEFF]", "", core)
        core = re.sub(r"[.·•\-–—_=~*※▪▫◇◆□■★☆♡♥\s]", "", core)
        core = re.sub(r"[\U00010000-\U0010FFFF\u2600-\u27BF]", "", core)
        return len(core) >= 2
    for l in lines:
        if meaningful(l):
            return l[:120] + ("…" if len(l) > 120 else "")
    return lines[0] if lines else "(제목 없음)"

def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

# ── 데이터 로드 ───────────────────────────────────────
def load_csv(key, local_dir=None):
    if local_dir:
        path = os.path.join(local_dir, f"{key}.csv")
        text = open(path, encoding="utf-8-sig").read()
    else:
        import requests
        r = requests.get(CSV[key], timeout=60)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))

# ── 분기 계산 ─────────────────────────────────────────
def quarter_range(q):
    y, n = q.split("-Q")
    y, n = int(y), int(n)
    start = dt.date(y, 3 * (n - 1) + 1, 1)
    end = dt.date(y + (n == 4), 1 if n == 4 else 3 * n + 1, 1) - dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()

def prev_quarter(q):
    y, n = q.split("-Q")
    y, n = int(y), int(n)
    return f"{y-1}-Q4" if n == 1 else f"{y}-Q{n-1}"

def default_quarter():
    d = NOW.date()
    n = (d.month - 1) // 3 + 1
    return prev_quarter(f"{d.year}-Q{n}")

# ── 모델 구성 (대시보드와 동일 규칙) ─────────────────
def build(daily_rows, post_rows, content_rows, analysis_rows):
    daily = {k: [] for k in CH_KEYS}
    for r in daily_rows:
        ch, d = (r.get("channel") or "").strip(), norm_date(r.get("date"))
        if ch in daily and d:
            daily[ch].append({"date": d, "views": to_int(r.get("views_day")), "reactions": to_int(r.get("reactions_day")),
                              "followers": to_int(r.get("followers"))})
    for k in daily:
        daily[k].sort(key=lambda x: x["date"])

    contents = {}
    for c in content_rows:
        cid = (c.get("content_id") or "").strip()
        if cid:
            contents[cid] = {"id": cid, "title": first_line(c.get("title")), "format": c.get("format") or "",
                             "date": norm_date(c.get("first_posted_at")), "perf": {}}
    for p in post_rows:
        cid, ch = (p.get("content_id") or "").strip(), (p.get("channel") or "").strip()
        if cid in contents and ch in CH:
            contents[cid]["perf"][ch] = {
                "views": to_int(p.get("views")), "likes": to_int(p.get("likes")), "comments": to_int(p.get("comments")),
                "shares": to_int(p.get("shares")), "saves": to_int(p.get("saves")), "url": p.get("url") or "",
                "posted_at": str(p.get("posted_at") or ""), "title": first_line(p.get("title_raw")),
            }
    items = []
    for c in contents.values():
        if not c["perf"]:
            continue
        for k in ["instagram", "youtube", "tiktok"]:      # 대표 제목: 인스타 우선
            if k in c["perf"] and c["perf"][k]["title"] not in ("", "(제목 없음)"):
                c["title"] = c["perf"][k]["title"]; break
        c["total"] = sum(p["views"] for p in c["perf"].values())
        c["eng"] = sum(p["likes"] + p["comments"] + p["shares"] + p["saves"] for p in c["perf"].values())
        c["channels"] = [k for k in CH_KEYS if k in c["perf"]]
        c["dates"] = {k: (norm_date(p["posted_at"]) or c["date"]) for k, p in c["perf"].items()}
        ds = sorted(d for d in c["dates"].values() if d)
        if ds:
            c["date"] = ds[0]
        items.append(c)

    # analysis: 연결 이력 별칭 + 삭제 반영
    alias = {}
    for a in analysis_rows:
        if (a.get("category") or "") == "연결" and a.get("value") and a.get("content_id"):
            alias[a["value"].strip()] = a["content_id"].strip()
    def resolve(x):
        n = 0
        while x in alias and n < 20:
            x = alias[x]; n += 1
        return x
    notes = []
    for a in analysis_rows:
        if (a.get("category") or "") == "연결":
            continue
        notes.append({"ts": norm_ts(a.get("timestamp")), "content_id": resolve((a.get("content_id") or "").strip()),
                      "author": a.get("author") or "익명", "type": a.get("type") or "분석",
                      "category": a.get("category") or "", "value": (a.get("value") or "").strip()})
    notes.sort(key=lambda a: a["ts"])
    tag_state, text_map = {}, {}
    for a in notes:
        if a["type"] == "태그":
            tag_state[a["content_id"] + "|" + a["value"]] = None if a["category"] == "삭제" else a
        else:
            text_map[a["content_id"] + "|" + a["author"] + "|" + a["value"]] = None if a["category"] == "삭제" else a
    tags = [a for a in tag_state.values() if a]
    texts = [a for a in text_map.values() if a]
    return daily, items, tags, texts

# ── 분석 ──────────────────────────────────────────────
def analyze(daily, items, tags, texts, q):
    s, e = quarter_range(q)
    ps, pe = quarter_range(prev_quarter(q))

    def span(k, a, b):
        rows = [d for d in daily[k] if a <= d["date"] <= b]
        return sum(d["views"] for d in rows), sum(d["reactions"] for d in rows)
    def snap(k, upto):
        f = 0
        for d in daily[k]:
            if d["date"] <= upto and d["followers"]:
                f = d["followers"]
        return f

    summary = {}
    for k in CH_KEYS:
        v, r = span(k, s, e); pv, pr = span(k, ps, pe)
        fo, pfo = snap(k, e), snap(k, ps and (dt.date.fromisoformat(s) - dt.timedelta(days=1)).isoformat())
        summary[k] = {"views": v, "reactions": r, "dv": pct(v, pv), "dr": pct(r, pr),
                      "followers": fo, "df": pct(fo, pfo), "has": bool(daily[k])}
    total = {"views": sum(x["views"] for x in summary.values()), "reactions": sum(x["reactions"] for x in summary.values()),
             "followers": sum(x["followers"] for x in summary.values())}
    pv = sum(span(k, ps, pe)[0] for k in CH_KEYS); pr = sum(span(k, ps, pe)[1] for k in CH_KEYS)
    total["dv"], total["dr"] = pct(total["views"], pv), pct(total["reactions"], pr)

    def in_q(d): return bool(d) and s <= d <= e
    qitems = [c for c in items if any(in_q(d) for d in c["dates"].values())]

    # 채널별 워킹 콘텐츠
    channel_top = {}
    for k in CH_KEYS:
        lst = [c for c in qitems if k in c["perf"] and in_q(c["dates"].get(k))]
        by_views = sorted(lst, key=lambda c: -c["perf"][k]["views"])[:5]
        by_eng = sorted(lst, key=lambda c: -(c["perf"][k]["likes"] + c["perf"][k]["comments"] + c["perf"][k]["shares"] + c["perf"][k]["saves"]))[:3]
        channel_top[k] = {"count": len(lst), "views": by_views, "eng": by_eng}

    # 태그 인사이트 (분기 게시 콘텐츠 기준, 없으면 전체 기준)
    base = qitems if len(qitems) >= 5 else items
    base_ids = {c["id"] for c in base}
    avg_v = sum(c["total"] for c in base) / len(base) if base else 0
    avg_e = sum(c["eng"] for c in base) / len(base) if base else 0
    tmap = defaultdict(set)
    for a in tags:
        if a["content_id"] in base_ids:
            tmap[a["value"]].add(a["content_id"])
    by_id = {c["id"]: c for c in base}
    tag_rows = []
    for t, ids in tmap.items():
        cs = [by_id[i] for i in ids]
        av = sum(c["total"] for c in cs) / len(cs); ae = sum(c["eng"] for c in cs) / len(cs)
        tag_rows.append({"tag": t, "n": len(cs), "avg_v": av, "avg_e": ae,
                         "xv": round(av / avg_v, 2) if avg_v else None, "xe": round(ae / avg_e, 2) if avg_e else None,
                         "top": sorted(cs, key=lambda c: -c["total"])[0]})
    tag_rows.sort(key=lambda r: (-r["n"], -r["avg_v"]))

    # 포맷별
    fmap = defaultdict(list)
    for c in qitems:
        fmap[c["format"] or "미분류"].append(c)
    format_rows = sorted([{"format": f, "n": len(l), "avg_v": sum(c["total"] for c in l) / len(l),
                           "avg_e": sum(c["eng"] for c in l) / len(l)} for f, l in fmap.items()], key=lambda r: -r["avg_v"])

    # 팀 분석 (분기 내 기록)
    by_cat = defaultdict(list)
    cmap = {c["id"]: c for c in items}
    for a in texts:
        if s <= a["ts"][:10] <= e and a["content_id"] in cmap:
            by_cat[a["category"] or "기타"].append({**a, "title": cmap[a["content_id"]]["title"]})

    # 게시 시간대 (분기 게시물, 참여 평균)
    slots = defaultdict(lambda: [0, 0])
    days = ["월", "화", "수", "목", "금", "토", "일"]
    for c in qitems:
        for k, p in c["perf"].items():
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):", p["posted_at"])
            if not m:
                continue
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            h = int(m.group(4)) + 9 if "Z" in p["posted_at"] or "+0000" in p["posted_at"] else int(m.group(4))
            h %= 24
            slot = "오전" if h < 12 else ("오후" if h < 18 else "저녁")
            key = f"{days[d.weekday()]} {slot}"
            slots[key][0] += p["likes"] + p["comments"] + p["shares"] + p["saves"]; slots[key][1] += 1
    slot_rows = sorted([{"slot": k, "n": v[1], "avg": v[0] / v[1]} for k, v in slots.items() if v[1] >= 2],
                       key=lambda r: -r["avg"])[:3]

    # 규칙 기반 제언
    tips = []
    best_ch = max(CH_KEYS, key=lambda k: (summary[k]["dv"] or -999))
    if summary[best_ch]["dv"] is not None:
        tips.append(f"{CH[best_ch]['name']} 조회수가 전 분기 대비 {summary[best_ch]['dv']:+.1f}%로 가장 크게 움직였습니다. 해당 채널의 상위 콘텐츠 유형을 다음 분기 우선 편성 후보로 검토해볼 만합니다.")
    strong = [r for r in tag_rows if r["n"] >= 2 and r["xv"] and r["xv"] >= 1.3]
    if strong:
        r = strong[0]
        tips.append(f"#{r['tag']} 태그 콘텐츠({r['n']}편)는 평균 조회가 전체의 {r['xv']}배입니다. 이 요소를 포함한 콘텐츠 비중을 늘리는 실험을 제안합니다.")
    if len(format_rows) >= 2:
        a, b = format_rows[0], format_rows[-1]
        tips.append(f"포맷별로는 {a['format']}(평균 조회 {fmt(a['avg_v'])})이 {b['format']}({fmt(b['avg_v'])})보다 앞섰습니다. 제작 리소스 배분 시 참고할 수 있습니다.")
    if slot_rows:
        tips.append(f"게시 시간대는 {slot_rows[0]['slot']}의 평균 참여가 가장 높았습니다({slot_rows[0]['n']}건 기준). 예약 게시 기본값으로 검토해보세요.")
    if not tips:
        tips.append("비교할 전 분기 데이터가 쌓이면 자동 제언이 표시됩니다.")

    return {"q": q, "start": s, "end": e, "summary": summary, "total": total, "qitems": qitems,
            "channel_top": channel_top, "tag_rows": tag_rows, "avg_v": avg_v, "avg_e": avg_e, "tag_base_note": "" if len(qitems) >= 5 else " (분기 게시물이 적어 전체 콘텐츠 기준)",
            "format_rows": format_rows, "by_cat": by_cat, "slot_rows": slot_rows, "tips": tips}

# ── HTML 렌더 ─────────────────────────────────────────
CSS = """
*{box-sizing:border-box}body{margin:0;background:#F4F5F7;color:#1B1E23;font-family:'Pretendard Variable',Pretendard,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;line-height:1.55}
.wrap{max-width:900px;margin:0 auto;padding:32px 20px 60px}
.hero{background:#111216;color:#fff;border-radius:16px;padding:28px 30px;margin-bottom:24px}
.hero .k{font-size:11px;letter-spacing:.1em;color:#9AA0A8;font-weight:600}.hero h1{margin:6px 0 4px;font-size:26px;letter-spacing:-.02em}.hero .sub{color:#B8BDC5;font-size:13px}
h2{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:4px solid #1B1E23;letter-spacing:-.01em}
.card{background:#fff;border:1px solid #E3E6EA;border-radius:12px;padding:18px 20px;margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.kpi .l{font-size:12px;color:#6B7280;font-weight:600}.kpi .v{font-size:28px;font-weight:800;letter-spacing:-.02em;margin:4px 0 2px;font-variant-numeric:tabular-nums}.kpi .d{font-size:12px;color:#6B7280}
.up{color:#0E8A5F;font-weight:700}.down{color:#C2402A;font-weight:700}.muted{color:#9AA0A8}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;font-size:11.5px;color:#6B7280;font-weight:700;padding:8px 8px;border-bottom:1px solid #E3E6EA}td{padding:9px 8px;border-bottom:1px solid #F0F2F4;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:10px;margin-right:4px;color:#fff}
.tag{display:inline-block;background:#EEF0F3;border-radius:12px;padding:2px 9px;font-size:12px;font-weight:600;color:#3A3F47}
.bar{height:8px;background:#EEF0F3;border-radius:4px;overflow:hidden;margin-top:4px}.bar>i{display:block;height:100%;background:#4A6CF7;border-radius:4px}
.note{background:#F8F9FB;border:1px solid #E3E6EA;border-radius:8px;padding:10px 12px;margin-bottom:8px;font-size:13px}.note .m{font-size:11px;color:#6B7280;margin-bottom:3px}
.cat{font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:9px;background:#EEF0F3;margin-right:6px}
.tips li{margin-bottom:8px}a{color:#2E5BDA;text-decoration:none}a:hover{text-decoration:underline}
.foot{margin-top:40px;font-size:12px;color:#8A9098;text-align:center}
@media print{body{background:#fff}.hero{border-radius:0}.card{break-inside:avoid;border-color:#ccc}h2{break-after:avoid}a{color:#1B1E23}}
"""

def badge(k):
    return f'<span class="badge" style="background:{CH[k]["color"]}">{CH[k]["name"]}</span>'

def link(c, k=None):
    p = c["perf"].get(k) if k else None
    url = (p or {}).get("url") or next((v["url"] for v in c["perf"].values() if v.get("url")), "")
    title = (p or {}).get("title") if p and p.get("title") not in ("", "(제목 없음)") else c["title"]
    return f'<a href="{esc(url)}" target="_blank">{esc(title)}</a>' if url else esc(title)

def render(a):
    q, s, e = a["q"], a["start"], a["end"]
    t = a["total"]
    H = [f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SNS 분기 리포트 {q}</title>\n<meta http-equiv="Cache-Control" content="no-cache, must-revalidate">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>{CSS}</style></head><body><div class="wrap">
<div class="hero"><div class="k">COSMAX NBT · SOCIAL PERFORMANCE REPORT</div><h1>{q} SNS 분기 리포트</h1>
<div class="sub">{s} ~ {e} · 유튜브 · 인스타그램 · 틱톡 · 생성 {NOW:%Y-%m-%d %H:%M}</div></div>"""]

    # 1. 요약
    H.append("<h2>1. 분기 요약</h2><div class='grid'>")
    H.append(f"<div class='card kpi'><div class='l'>총 조회수</div><div class='v'>{fmt(t['views'])}</div><div class='d'>{arrow(t['dv'])} 전 분기 대비</div></div>")
    H.append(f"<div class='card kpi'><div class='l'>총 참여 수</div><div class='v'>{fmt(t['reactions'])}</div><div class='d'>{arrow(t['dr'])} 전 분기 대비</div></div>")
    H.append(f"<div class='card kpi'><div class='l'>전체 팔로워</div><div class='v'>{fmt(t['followers'])}</div><div class='d'>분기 말 기준</div></div>")
    H.append(f"<div class='card kpi'><div class='l'>게시 콘텐츠</div><div class='v'>{len(a['qitems'])}편</div><div class='d'>분기 내 게시</div></div></div>")
    H.append("<div class='card'><table><tr><th>채널</th><th class='n'>팔로워</th><th class='n'>증감</th><th class='n'>조회수</th><th class='n'>전 분기 대비</th><th class='n'>참여 수</th><th class='n'>전 분기 대비</th></tr>")
    for k in CH_KEYS:
        x = a["summary"][k]
        if not x["has"]:
            H.append(f"<tr><td>{badge(k)}</td><td colspan='6' class='muted'>수집 데이터 없음</td></tr>"); continue
        H.append(f"<tr><td>{badge(k)}</td><td class='n'>{fmt(x['followers']) if x['followers'] else '–'}</td><td class='n'>{arrow(x['df']) if x['followers'] else '–'}</td>"
                 f"<td class='n'>{fmt(x['views'])}</td><td class='n'>{arrow(x['dv'])}</td><td class='n'>{fmt(x['reactions'])}</td><td class='n'>{arrow(x['dr'])}</td></tr>")
    H.append("</table><div style='font-size:11.5px;color:#6B7280;margin-top:8px'>조회·참여 수 = 분기 중 채널에서 발생한 합계(옛 게시물 포함) · 참여 = 좋아요+댓글+공유+저장</div></div>")

    # 2. 채널별 워킹 콘텐츠
    H.append("<h2>2. 채널별 워킹 콘텐츠</h2>")
    for k in CH_KEYS:
        ct = a["channel_top"][k]
        H.append(f"<div class='card'><div style='font-weight:700;margin-bottom:8px'>{badge(k)} 분기 게시 {ct['count']}편</div>")
        if not ct["views"]:
            H.append("<div class='muted' style='font-size:13px'>분기 내 게시물이 없습니다.</div></div>"); continue
        H.append("<table><tr><th>#</th><th>조회수 TOP 5</th><th class='n'>게시일</th><th class='n'>조회수</th><th class='n'>참여</th></tr>")
        for i, c in enumerate(ct["views"], 1):
            p = c["perf"][k]; eng = p["likes"] + p["comments"] + p["shares"] + p["saves"]
            cross = f' <span class="tag" style="font-size:10px">교차 {len(c["channels"])}채널</span>' if len(c["channels"]) > 1 else ""
            H.append(f"<tr><td class='muted'>{i}</td><td>{link(c, k)}{cross}</td><td class='n muted'>{c['dates'].get(k) or c['date']}</td><td class='n'><b>{fmt(p['views'])}</b></td><td class='n'>{fmt(eng)}</td></tr>")
        H.append("</table>")
        if ct["eng"]:
            H.append("<div style='font-size:12px;color:#6B7280;margin-top:10px'>참여 수 기준 TOP 3: " + " · ".join(f"{link(c, k)} ({fmt(c['perf'][k]['likes']+c['perf'][k]['comments']+c['perf'][k]['shares']+c['perf'][k]['saves'])})" for c in ct["eng"]) + "</div>")
        H.append("</div>")

    # 3. 태그 인사이트
    H.append(f"<h2>3. 태그 인사이트{a['tag_base_note']}</h2><div class='card'>")
    if not a["tag_rows"]:
        H.append("<div class='muted' style='font-size:13px'>아직 태그가 등록된 콘텐츠가 없습니다. 대시보드 콘텐츠 성과 탭에서 태그를 달면 다음 리포트부터 집계됩니다.</div>")
    else:
        mx = max(r["avg_v"] for r in a["tag_rows"]) or 1
        H.append(f"<div style='font-size:12px;color:#6B7280;margin-bottom:10px'>기준 평균: 조회 {fmt(a['avg_v'])} · 참여 {fmt(a['avg_e'])} (콘텐츠당)</div>")
        H.append("<table><tr><th>태그</th><th class='n'>편수</th><th>평균 조회수</th><th class='n'>전체 대비</th><th class='n'>평균 참여</th><th class='n'>전체 대비</th><th>대표 콘텐츠</th></tr>")
        for r in a["tag_rows"]:
            xv = f"{r['xv']}배" if r["xv"] else "–"; xe = f"{r['xe']}배" if r["xe"] else "–"
            cls_v = "up" if (r["xv"] or 0) >= 1 else "down"; cls_e = "up" if (r["xe"] or 0) >= 1 else "down"
            H.append(f"<tr><td><span class='tag'>#{esc(r['tag'])}</span></td><td class='n'>{r['n']}</td>"
                     f"<td style='min-width:140px'><b>{fmt(r['avg_v'])}</b><div class='bar'><i style='width:{r['avg_v']/mx*100:.0f}%'></i></div></td>"
                     f"<td class='n {cls_v}'>{xv}</td><td class='n'>{fmt(r['avg_e'])}</td><td class='n {cls_e}'>{xe}</td><td style='font-size:12px'>{link(r['top'])}</td></tr>")
        H.append("</table>")
    H.append("</div>")

    # 4. 포맷별
    H.append("<h2>4. 포맷별 성과</h2><div class='card'>")
    if a["format_rows"]:
        H.append("<table><tr><th>포맷</th><th class='n'>편수</th><th class='n'>평균 조회수</th><th class='n'>평균 참여</th></tr>")
        for r in a["format_rows"]:
            H.append(f"<tr><td>{esc(r['format'])}</td><td class='n'>{r['n']}</td><td class='n'><b>{fmt(r['avg_v'])}</b></td><td class='n'>{fmt(r['avg_e'])}</td></tr>")
        H.append("</table><div style='font-size:11.5px;color:#6B7280;margin-top:8px'>이미지(카드뉴스)와 영상은 조회수 산정 방식이 달라 포맷 간 직접 비교는 참고용입니다.</div>")
    else:
        H.append("<div class='muted' style='font-size:13px'>분기 내 게시물이 없습니다.</div>")
    H.append("</div>")

    # 5. 팀 분석
    H.append("<h2>5. 팀 분석 하이라이트</h2><div class='card'>")
    if not a["by_cat"]:
        H.append("<div class='muted' style='font-size:13px'>분기 중 등록된 팀 분석이 없습니다.</div>")
    for cat in ["성과 요인", "개선점", "후속 아이디어", "기타"]:
        lst = a["by_cat"].get(cat)
        if not lst:
            continue
        H.append(f"<div style='font-weight:700;margin:10px 0 6px'>{cat} <span class='muted' style='font-weight:400;font-size:12px'>· {len(lst)}건</span></div>")
        for n in lst[-8:]:
            H.append(f"<div class='note'><div class='m'>{esc(n['author'])} · {n['ts'][:10]} · {esc(n['title'])}</div>{esc(n['value'])}</div>")
    H.append("</div>")

    # 6. 시간대
    H.append("<h2>6. 게시 시간대</h2><div class='card'>")
    if a["slot_rows"]:
        H.append("<table><tr><th>요일 · 시간대</th><th class='n'>게시 수</th><th class='n'>평균 참여</th></tr>")
        for r in a["slot_rows"]:
            H.append(f"<tr><td>{esc(r['slot'])}</td><td class='n'>{r['n']}</td><td class='n'><b>{fmt(r['avg'])}</b></td></tr>")
        H.append("</table><div style='font-size:11.5px;color:#6B7280;margin-top:8px'>오전 = 0~12시 · 오후 = 12~18시 · 저녁 = 18~24시 · 2건 이상 게시된 시간대만 집계</div>")
    else:
        H.append("<div class='muted' style='font-size:13px'>집계 가능한 게시 시각 데이터가 부족합니다.</div>")
    H.append("</div>")

    # 7. 제언
    H.append("<h2>7. 다음 분기 제언</h2><div class='card'><ul class='tips'>")
    for tip in a["tips"]:
        H.append(f"<li>{esc(tip)}</li>")
    H.append("</ul><div style='font-size:11.5px;color:#6B7280'>데이터 규칙 기반 자동 제언입니다. 팀 판단과 함께 활용하세요.</div></div>")

    H.append(f"<div class='foot'>이 리포트는 매 분기 첫날 자동 생성됩니다 · <a href='{DASHBOARD_URL}'>실시간 대시보드 열기</a> · <a href='./'>리포트 목록</a></div></div></body></html>")
    return "".join(H)

def render_index(entries):
    rows = "".join(f"<div class='card'><a href='{e['file']}'><b>{e['title']}</b></a><div style='font-size:12px;color:#6B7280;margin-top:4px'>{e['range']} · 생성 {e['generated_at']}</div></div>" for e in entries)
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SNS 분기 리포트</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"><style>{CSS}</style></head>
<body><div class="wrap"><div class="hero"><div class="k">COSMAX NBT</div><h1>SNS 분기 리포트</h1><div class="sub">분기별 자동 생성 리포트 아카이브</div></div>{rows or "<div class='card muted'>아직 생성된 리포트가 없습니다.</div>"}
<div class="foot"><a href="{DASHBOARD_URL}">실시간 대시보드 열기</a></div></div></body></html>"""

# ── 메인 ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarter", default=None, help="예: 2026-Q3 (기본: 직전 분기)")
    ap.add_argument("--local", default=None, help="로컬 CSV 폴더 (daily.csv, posts.csv, contents.csv, analysis.csv)")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    q = args.quarter or default_quarter()
    if not re.match(r"^\d{4}-Q[1-4]$", q):
        sys.exit("--quarter 형식: YYYY-Qn (예: 2026-Q3)")

    daily_rows = load_csv("daily", args.local)
    post_rows = load_csv("posts", args.local)
    content_rows = load_csv("contents", args.local)
    try:
        analysis_rows = load_csv("analysis", args.local)
    except Exception:
        analysis_rows = []

    daily, items, tags, texts = build(daily_rows, post_rows, content_rows, analysis_rows)
    a = analyze(daily, items, tags, texts, q)
    html = render(a)

    os.makedirs(args.out, exist_ok=True)
    fname = f"{q}.html"
    open(os.path.join(args.out, fname), "w", encoding="utf-8").write(html)

    idx_path = os.path.join(args.out, "index.json")
    entries = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else []
    entries = [e for e in entries if e.get("quarter") != q]
    entries.append({"quarter": q, "title": f"{q} SNS 분기 리포트", "file": fname,
                    "range": f"{a['start']} ~ {a['end']}", "generated_at": NOW.strftime("%Y-%m-%d %H:%M")})
    entries.sort(key=lambda e: e["quarter"], reverse=True)
    json.dump(entries, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(args.out, "index.html"), "w", encoding="utf-8").write(render_index(entries))
    print(f"생성 완료: {args.out}/{fname} · 분기 게시 {len(a['qitems'])}편 · 태그 {len(a['tag_rows'])}종 · 분석 {sum(len(v) for v in a['by_cat'].values())}건")

if __name__ == "__main__":
    main()
