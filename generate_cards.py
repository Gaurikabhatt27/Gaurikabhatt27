from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path("assets")
OUT.mkdir(exist_ok=True)

MIDNIGHT, DARK, BURG = "#10070C", "#190B12", "#451126"
WINE, ROSE, PALE, IVORY = "#701A3D", "#C77B9B", "#E5B5C7", "#F8F0F3"
SERIF = "Georgia, 'Times New Roman', serif"
SANS = "Helvetica, Arial, sans-serif"

DEFS = f'''<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{MIDNIGHT}"/>
      <stop offset="0.6" stop-color="{DARK}"/>
      <stop offset="1" stop-color="{BURG}"/>
    </linearGradient>
    <linearGradient id="ln" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{WINE}"/>
      <stop offset="0.5" stop-color="{ROSE}"/>
      <stop offset="1" stop-color="{PALE}"/>
    </linearGradient>
  </defs>'''


def svg(w, h, body, label):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" role="img" aria-label="{escape(label)}">\n'
        f'  {DEFS}\n'
        f'  <rect width="{w}" height="{h}" rx="14" fill="url(#bg)"/>\n'
        f'  <rect width="{w}" height="{h}" rx="14" fill="none" stroke="{ROSE}" stroke-opacity="0.35"/>\n'
        f'{body}\n</svg>\n'
    )


def text(x, y, s, size, fill, family=SANS, extra=""):
    return (f'  <text x="{x}" y="{y}" font-family="{family}" '
            f'font-size="{size}" fill="{fill}" {extra}>{escape(s)}</text>')


def header(name, label, title, tagline):
    w, h = 1000, 180
    body = f'''  <rect width="{w}" height="{h}" rx="16" fill="url(#hd-bg)"/>
  <rect width="{w}" height="{h}" rx="16" fill="url(#hd-glow)"/>
  <rect width="{w}" height="{h}" rx="16" fill="url(#hd-grid)"/>
  <rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="16" fill="none" stroke="{ROSE}" stroke-opacity="0.4"/>
  <circle cx="900" cy="90" r="70" fill="none" stroke="{ROSE}" stroke-opacity="0.25"/>
  <circle cx="900" cy="90" r="42" fill="none" stroke="{PALE}" stroke-opacity="0.2" stroke-dasharray="4 6"/>
{text(44, 48, label, 13, ROSE, SANS, 'letter-spacing="3"')}
{text(44, 108, title, 50, IVORY, SERIF)}
  <rect x="44" y="124" width="260" height="2" fill="url(#hd-ln)"/>
{text(44, 152, tagline, 15, PALE, SANS, 'font-style="italic"')}
'''
    defs = f'''<defs>
    <linearGradient id="hd-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{MIDNIGHT}"/>
      <stop offset="0.6" stop-color="{DARK}"/>
      <stop offset="1" stop-color="{BURG}"/>
    </linearGradient>
    <radialGradient id="hd-glow" cx="0.85" cy="0.3" r="0.6">
      <stop offset="0" stop-color="{ROSE}" stop-opacity="0.35"/>
      <stop offset="1" stop-color="{ROSE}" stop-opacity="0"/>
    </radialGradient>
    <pattern id="hd-grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M40 0H0V40" fill="none" stroke="{PALE}" stroke-opacity="0.07"/>
    </pattern>
    <linearGradient id="hd-ln" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{WINE}"/>
      <stop offset="0.5" stop-color="{ROSE}"/>
      <stop offset="1" stop-color="{PALE}"/>
    </linearGradient>
  </defs>'''
    svg_text = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" role="img" aria-label="{escape(title)}">\n'
        f'  {defs}\n{body}</svg>\n'
    )
    (OUT / f"h-{name}.svg").write_text(svg_text, encoding="utf-8")


HEADERS = [
    ("about", "01 · ABOUT", "About Me",
     "Turning complex data into meaningful insights."),
    ("achievements", "02 · RECOGNITION", "Achievements",
     "Milestones from university, competitions and open source."),
    ("projects", "03 · SELECTED WORK", "Featured Projects",
     "Products and analyses built from problem to solution."),
    ("skills", "04 · STACK", "Technical Skills",
     "Tools I use across data, machine learning and development."),
    ("stats", "05 · GITHUB", "GitHub Analytics",
     "Live activity from my GitHub account."),
    ("connect", "06 · CONNECT", "Let's Connect",
     "Open to learning, collaboration and opportunities."),
]

def card(i, title, lines, tech):
    body = "\n".join([
        text(24, 34, f"{i:02d} · PROJECT", 11, ROSE, SANS, 'letter-spacing="2"'),
        text(24, 66, title, 21, IVORY, SERIF),
        *[text(24, 94 + n * 19, s, 13, PALE) for n, s in enumerate(lines)],
        '  <rect x="24" y="140" width="392" height="1" fill="url(#ln)"/>',
        text(24, 162, tech, 11, ROSE),
    ])
    (OUT / f"card-{i}.svg").write_text(svg(440, 180, body, title), encoding="utf-8")



PROJECTS = [
    (1, "LYRA", ["Desktop voice assistant for voice-controlled", "interactions, web automation and productivity."],
     "Python · Groq · Cohere · Selenium · PyQt5 · Edge TTS"),
    (2, "EchoChamber", ["Real-time debate platform with AI-powered", "moderation and live communication."],
     "React · Node.js · Express · MongoDB · Socket.io · Redis"),
    (3, "Public Transport Ridership", ["Forecasts hourly bus ridership from NYC transit,", "weather and calendar data."],
     "Python · PySpark · Spark MLlib · Pandas · Power BI"),
    (4, "India Socio-Demographic Insights", ["Interactive dashboards exploring Census 2011", "patterns across India."],
     "Power BI · Data Analytics · Excel"),
    (5, "Smart Course Recommendation", ["Recommends courses from student skills, interests", "and ratings, with learning analytics."],
     "Python · MongoDB · Streamlit · Pandas · Plotly"),
    (6, "Heart Disease Prediction", ["Logistic Regression model that estimates heart", "disease risk from patient health attributes."],
     "Python · Pandas · NumPy · Scikit-learn · Matplotlib"),
    (7, "Shark Tank Analysis", ["EDA of Shark Tank deals to uncover patterns", "in startup funding and investor behaviour."],
     "Python · Pandas · NumPy · Matplotlib · Seaborn"),
]

for name, label, title, tagline in HEADERS:
    header(name, label, title, tagline)
    print(f"wrote assets/h-{name}.svg")

for i, title, lines, tech in PROJECTS:
    card(i, title, lines, tech)
    print(f"wrote assets/card-{i}.svg")

print("Done. Open the files in a browser to check them.")