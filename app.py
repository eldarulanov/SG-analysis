import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import fitz  # PyMuPDF
from openai import OpenAI
import markdown
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
print("Using DB at:", app.config["SQLALCHEMY_DATABASE_URI"])
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
    founders = db.Column(db.Text)  # simple string for now
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

# --- OpenAI Call ---
# --- OpenAI Call ---
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


# --- ROUTES ---

@app.route("/")
def dashboard():
    startups = Startup.query.all()
    return render_template("dashboard.html", startups=startups)

@app.route("/add", methods=["GET", "POST"])
def add_startup():
    if request.method == "POST":
        file = request.files.get("deck_file")
        filename = None
        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

        new = Startup(
            name=request.form["name"],
            industry=request.form["industry"],
            stage=request.form["stage"],
            assigned_gp=request.form["assigned_gp"],
            contact_person=request.form["contact_person"],
            status="Submitted",
            deck_file=filename  # store file name in DB
        )
        db.session.add(new)
        db.session.commit()
        return redirect(url_for("dashboard"))

    return render_template("add_startup.html")


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

    html_memo = markdown.markdown(memo_text)
    output_filename = f"{startup.name}_memo.pdf"
    output_path = os.path.join(app.config["OUTPUT_FOLDER"], output_filename)

    html_content = render_template("pdf_template.html", memo_html=html_memo, startup=startup.name)
    HTML(string=html_content).write_pdf(output_path)

    startup.memo_pdf = output_filename
    db.session.commit()

    return redirect(url_for("view_startup", startup_id=startup.id))

@app.route("/outputs/<filename>")
def download_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

# --- Run ---
if __name__ == "__main__":
    with app.app_context():
        db.drop_all()    # start fresh every time you run
        db.create_all()
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        print("Tables in DB:", inspector.get_table_names())
    app.run(debug=True)
