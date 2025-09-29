import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import fitz  # PyMuPDF
from openai import OpenAI
import markdown_it
from mdit_py_plugins.gfm import gfm_plugin
from weasyprint import HTML

# --- Setup ---
load_dotenv()
app = Flask(__name__)

# File storage
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "outputs"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

# Database setup
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///startups.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Database Model ---
class Startup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    industry = db.Column(db.String(100))
    stage = db.Column(db.String(50))
    assigned_gp = db.Column(db.String(100))
    contact_person = db.Column(db.String(100))
    founders = db.Column(db.Text)
    arr = db.Column(db.Float)
    funding = db.Column(db.Float)
    valuation = db.Column(db.Float)
    gp_notes = db.Column(db.Text)
    score_market = db.Column(db.Integer)
    score_product = db.Column(db.Integer)
    score_traction = db.Column(db.Integer)
    score_team = db.Column(db.Integer)
    score_competition = db.Column(db.Integer)
    score_scalability = db.Column(db.Integer)
    score_exit = db.Column(db.Integer)
    overall_score = db.Column(db.Float)
    status = db.Column(db.String(50))
    memo_pdf = db.Column(db.String(200))
    deck_file = db.Column(db.String(200))

# --- PDF TEXT EXTRACTION ---
def extract_text(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text("text")
    return text.strip()

# --- Extract Startup Info ---
def extract_startup_info(deck_text):
    prompt = f"""
    You are an assistant that extracts key startup information from pitch decks.

    Pitch Deck Extract:
    {deck_text[:3000]}  # limited to avoid token overflow

    Task:
    - Extract the startup's **Name** and **Industry**.
    - Reply ONLY in JSON with keys: name, industry.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    try:
        content = response.choices[0].message.content.strip()
        import json
        data = json.loads(content)
        return data.get("name", ""), data.get("industry", "")
    except Exception as e:
        print("Extraction error:", e, "Response:", content)
        return "", ""

# --- OpenAI Call for Memo ---
def generate_memo(startup_name, industry, deck_text):
    prompt = f"""
You are an expert venture capital analyst preparing an investment committee (IC) style memo.

Startup: {startup_name}
Industry: {industry}
Pitch Deck Extract: {deck_text}

Instructions:
1. Write a **structured, data-heavy investment memo** in professional style.
2. Use **outside data sources** (market reports, recent funding rounds, competitor valuations, growth benchmarks) where possible. If no precise figure is available, use reasoned industry averages and state the source region/year clearly.
3. Include **citations/sources** at the end of each major section.
4. Avoid placeholders like "n/a" — leave cells blank if unknown.

Sections (in this order):
- Executive Summary  
  - Bullet points with ARR ($), MoM Growth (%), Gross Margin (%), Valuation ($), Funding to Date ($), and clear Recommendation.  
  - 1–2 paragraphs summarizing opportunity, risks, and rationale.  

- Industry Landscape  
  - Market size, CAGR, drivers, regional trends, and tailwinds/headwinds.  
  - At least 3 external sources referenced.  

- Pain Points  
  - List the core customer problems.  

- Competitive Landscape (Porter’s 5 Forces)  
  - Each force explained with references.  

- Comparator Table  
  - Include **as many relevant direct and indirect competitors as possible** (at least 5 rows if available).  
  - Columns: Competitor | ARR ($) | Funding ($) | Valuation ($) | HQ | Year Founded | Notes (strategic position, differentiator).  

- White Space Opportunities  
  - 3–5 expansion paths or product vectors.  

- Benchmarks & Multiples  
  - Include revenue multiples, ARR multiples, recent exits in the industry, and any valuation comparables.  

- GTM Strategy  
  - Analyze startup’s motion, channels, partnerships, and bottlenecks.  

- ROI Evidence  
  - Quantify payback period, unit economics, margins, efficiency gains.  

- Regulatory Readiness  
  - Relevant licenses, compliance risks, or certifications required.  

- Exit Paths  
  - Acquisition targets, IPO potential, or strategic tuck-ins.  

- Quantitative Scoring Matrix  
  - A table with 0–10 scores for: Market, Product, Traction, Team, Competition, Scalability, Exit Potential.  
  - Conclude with weighted overall score and short summary paragraph.  

Formatting Rules:
- Use **Markdown headings (##)** for sections.  
- Use bullet points for lists.  
- Tables must be clean and properly aligned.  
- Keep writing professional, fact-based, and concise, but rich with data.  
- Always end each section with a short line of **Sources** (e.g. Sources: Crunchbase, Pitchbook 2024, Statista).  
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content

# --- Routes ---
@app.route("/")
def dashboard():
    startups = Startup.query.all()
    return render_template("dashboard.html", startups=startups)

@app.route("/upload", methods=["GET", "POST"])
def upload_pitchdeck():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.endswith(".pdf"):
            return "Please upload a valid PDF", 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        deck_text = extract_text(filepath)
        name, industry = extract_startup_info(deck_text)

        return render_template(
            "confirm_startup.html",
            filename=filename,
            name=name,
            industry=industry
        )
    return render_template("upload.html")

@app.route("/confirm", methods=["POST"])
def confirm_startup():
    filename = request.form["filename"]
    startup = Startup(
        name=request.form["name"],
        industry=request.form["industry"],
        assigned_gp=request.form["assigned_gp"],
        contact_person=request.form["contact_person"],
        status="Submitted",
        deck_file=filename
    )
    db.session.add(startup)
    db.session.commit()
    return redirect(url_for("dashboard"))

@app.route("/startup/<int:startup_id>")
def view_startup(startup_id):
    startup = Startup.query.get_or_404(startup_id)
    return render_template("startup.html", startup=startup)

@app.route("/generate_memo/<int:startup_id>")
def generate_memo_for_startup(startup_id):
    startup = Startup.query.get_or_404(startup_id)
    if not startup.deck_file:
        return "No pitch deck uploaded", 400

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], startup.deck_file)
    deck_text = extract_text(filepath)
    memo_text = generate_memo(startup.name, startup.industry, deck_text)

    # Render Markdown with GitHub-flavored tables
    md = markdown_it.MarkdownIt().use(gfm_plugin)
    html_memo = md.render(memo_text)

    # Save as PDF
    output_filename = f"{startup.name}_memo.pdf"
    output_path = os.path.join(app.config["OUTPUT_FOLDER"], output_filename)

    html_content = render_template("pdf_template.html", memo_html=html_memo, startup=startup.name)
    HTML(string=html_content).write_pdf(output_path)

    # Save memo + PDF path in DB
    startup.memo_pdf = output_filename
    startup.gp_notes = memo_text  # store raw markdown
    db.session.commit()

    return render_template(
        "result.html",
        memo_html=html_memo,
        download_link=url_for("download_file", filename=output_filename)
    )


@app.route("/outputs/<filename>")
def download_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

# --- Run ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # only create tables if they don’t exist
    app.run(debug=True)

