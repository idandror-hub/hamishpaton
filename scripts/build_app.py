#!/usr/bin/env python3
"""Build כלי נספחים.app on the Desktop"""

import os, subprocess, shutil

HOME = os.path.expanduser("~")
APP_DEST = os.path.join(HOME, "Desktop", "כלי נספחים.app")
PROJECT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── AppleScript launcher ─────────────────────────────────────────────────
ASCRIPT = f'''-- כלי נספחים משפטיים
set serverPort to "5050"

-- Check if server already responds
set isRunning to false
try
    do shell script "curl -s -f --max-time 1 http://localhost:" & serverPort & "/ > /dev/null"
    set isRunning to true
end try

-- Start if needed
if not isRunning then
    do shell script "nohup /bin/bash \\"{PROJECT}/run.sh\\" >> /tmp/legal-tool.log 2>&1 &"
    -- Wait up to 15 s for Flask to be ready
    repeat 15 times
        delay 1
        try
            do shell script "curl -s -f --max-time 1 http://localhost:" & serverPort & "/ > /dev/null"
            exit repeat
        end try
    end repeat
end if

open location "http://localhost:" & serverPort
'''

# ── Icon via reportlab → PDF → PNG → ICNS ───────────────────────────────
def make_icon():
    pdf = '/tmp/_legal_icon.pdf'
    try:
        from reportlab.pdfgen import canvas as C
        from reportlab.lib.colors import HexColor, white

        S = 512.0
        c = C.Canvas(pdf, pagesize=(S, S))

        # Blue rounded-rect background
        c.setFillColor(HexColor('#1a56db'))
        c.roundRect(0, 0, S, S, radius=S*0.16, fill=1, stroke=0)

        dw, dh = S*0.43, S*0.55
        dx = (S - dw) / 2
        dy = (S - dh) / 2
        fold = S * 0.11

        # Document drop shadow
        c.setFillColor(HexColor('#1240a8'))
        p = c.beginPath()
        p.moveTo(dx+6, dy-6); p.lineTo(dx+6, dy+dh-6)
        p.lineTo(dx+dw+6, dy+dh-6); p.lineTo(dx+dw+6, dy+fold-6)
        p.lineTo(dx+dw-fold+6, dy-6); p.close()
        c.drawPath(p, fill=1, stroke=0)

        # White document body (with folded top-right corner)
        c.setFillColor(white)
        p = c.beginPath()
        p.moveTo(dx, dy); p.lineTo(dx, dy+dh)
        p.lineTo(dx+dw, dy+dh); p.lineTo(dx+dw, dy+fold)
        p.lineTo(dx+dw-fold, dy); p.close()
        c.drawPath(p, fill=1, stroke=0)

        # Fold triangle (light blue)
        c.setFillColor(HexColor('#bfdbfe'))
        p = c.beginPath()
        p.moveTo(dx+dw-fold, dy)
        p.lineTo(dx+dw, dy+fold)
        p.lineTo(dx+dw-fold, dy+fold); p.close()
        c.drawPath(p, fill=1, stroke=0)

        # Text lines
        c.setFillColor(HexColor('#60a5fa'))
        lx1 = dx + dw*0.12;  lx2 = dx + dw*0.83
        ly0  = dy + dh*0.72; lh  = dh*0.042; lspc = dh*0.115
        for i in range(4):
            le = lx2 if i < 3 else (dx + dw*0.57)
            c.rect(lx1, ly0 - i*lspc, le-lx1, lh, fill=1, stroke=0)

        c.save()
    except Exception as e:
        print(f"  [icon] reportlab error: {e} — using default icon")
        return None

    # Convert PDF → PNG via sips
    png = '/tmp/_legal_icon_512.png'
    r = subprocess.run(['sips', '-s', 'format', 'png', '--out', png, pdf],
                       capture_output=True)
    if r.returncode != 0:
        print(f"  [icon] sips error: {r.stderr.decode()}")
        return None

    # Build iconset
    iconset = '/tmp/_legal.iconset'
    os.makedirs(iconset, exist_ok=True)
    specs = [
        ('icon_16x16.png',    16), ('icon_16x16@2x.png',   32),
        ('icon_32x32.png',    32), ('icon_32x32@2x.png',   64),
        ('icon_128x128.png', 128), ('icon_128x128@2x.png',256),
        ('icon_256x256.png', 256), ('icon_256x256@2x.png',512),
        ('icon_512x512.png', 512),
    ]
    for fname, sz in specs:
        subprocess.run(
            ['sips', '-z', str(sz), str(sz), png, '--out', os.path.join(iconset, fname)],
            capture_output=True)

    icns = '/tmp/_legal.icns'
    r = subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', icns], capture_output=True)
    if r.returncode != 0:
        print(f"  [icon] iconutil error: {r.stderr.decode()}")
        return None

    print("✓ Icon created")
    return icns


def build():
    # 1. Write AppleScript to temp file
    scr = '/tmp/_legal_launcher.applescript'
    with open(scr, 'w', encoding='utf-8') as f:
        f.write(ASCRIPT)

    # 2. Remove existing app
    if os.path.exists(APP_DEST):
        shutil.rmtree(APP_DEST)

    # 3. Compile to .app
    r = subprocess.run(['osacompile', '-o', APP_DEST, scr], capture_output=True)
    if r.returncode != 0:
        print("✗ osacompile failed:", r.stderr.decode())
        return
    print(f"✓ App compiled")

    # 4. Ad-hoc code-sign so Gatekeeper doesn't block it
    subprocess.run(['codesign', '--deep', '--sign', '-', '--force', APP_DEST],
                   capture_output=True)
    print("✓ Signed")

    # 5. Install icon
    icns = make_icon()
    if icns:
        resources = os.path.join(APP_DEST, 'Contents', 'Resources')
        shutil.copy(icns, os.path.join(resources, 'applet.icns'))

    # 6. Refresh Dock/Finder icon cache
    subprocess.run(['touch', APP_DEST])
    subprocess.run(['killall', 'Dock'], stderr=subprocess.DEVNULL)

    print(f"\n✅  כלי נספחים.app מוכן על שולחן העבודה")
    print("    לחץ פעמיים → השרת עולה → הדפדפן נפתח אוטומטית")
    print("    (בפעם הראשונה: לחץ ימני → פתח → פתח)")


build()
