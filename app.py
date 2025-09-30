import os
import re
import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import fitz  # PyMuPDF
from openai import OpenAI
import markdown_it
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

# --- Industry categories ---
INDUSTRY_CATEGORIES = [
    "MarTech", "E-commerce", "AdTech", "Space & Defense Tech", "VR/AR Tech", "FinTech",
    "HealthTech", "EdTech", "CleanTech", "Mobility & Transportation", "Logistics & Supply Chain",
    "Cybersecurity", "Blockchain", "SaaS", "Gaming & Entertainment", "Food and Agriculture Tech",
    "Telecommunications", "Service Industry (Consulting / Legal / Accounting etc...)", 
    "Data & Analytics", "Other"
]

def extract_startup_info(deck_text, file_name=""):
    # Prioritize first page text
    first_slide_text = deck_text.split("\n")[:40]  # first ~40 lines
    first_slide_text = " ".join(first_slide_text)

    # Clean file name for fallback
    clean_filename = os.path.splitext(os.path.basename(file_name))[0].replace("_", " ")

    prompt = f"""
    You are a VC analyst. Identify:
    1. The **startup name** (prefer first slide text; if unclear, fallback to file name: "{clean_filename}").
    2. The **industry**. Choose exactly one from this list:
    {INDUSTRY_CATEGORIES}

    Text to analyze:
    {first_slide_text[:2000]}

    Rules:
    - Respond ONLY in valid JSON (no commentary).
    - Keys: "name", "industry".
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    content = response.choices[0].message.content.strip()

    try:
        data = json.loads(content)
        name = data.get("name") or clean_filename
        industry = data.get("industry") if data.get("industry") in INDUSTRY_CATEGORIES else "Other"
        return name, industry
    except:
        print("⚠️ Fallback, raw response:", content)
        return clean_filename, "Other"

# --- Memo generation (section by section) ---
MEMO_SECTIONS = [
    "Executive Summary",
    "Industry Landscape",
    "Pain Points",
    "Competitive Landscape (Porter’s 5 Forces)",
    "Comparator Table",
    "White Space Opportunities",
    "Benchmarks & Multiples",
    "GTM Strategy",
    "ROI Evidence",
    "Regulatory Readiness",
    "Exit Paths",
    "Quantitative Scoring Matrix"
]

def generate_section(section_title, startup_name, industry, deck_text):
    prompt = f"""
    You are a VC analyst. Write the section **{section_title}** of an investment memo.

    Startup: {startup_name}
    Industry: {industry}
    Pitch Deck Extract (truncated): {deck_text[:3000]}

    Rules:
    - Use professional, data-driven tone.
    - Always format with Markdown (## headers, bullet points, tables where needed).
    - If citing sources, add them at the end of the section under "Sources".
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()

def generate_full_memo(startup_name, industry, deck_text):
    memo_parts = []
    for section in MEMO_SECTIONS:
        try:
            section_text = generate_section(section, startup_name, industry, deck_text)
            memo_parts.append(f"## {section}\n\n{section_text}")
        except Exception as e:
            memo_parts.append(f"## {section}\n\nError generating section: {e}")
    return "\n\n".join(memo_parts)

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
        name, industry = extract_startup_info(deck_text, filename)

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
        assigned_gp=request.form.get("assigned_gp", ""),
        contact_person=request.form.get("contact_person", ""),
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
    deck_text = extract_text(filepath)[:5000]  # truncate

    memo_text = generate_full_memo(startup.name, startup.industry, deck_text)

    # Render Markdown with GitHub-flavored tables
    md = markdown_it.MarkdownIt()
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
