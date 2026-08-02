from flask import Blueprint, request, jsonify

from models import Article

article_bp = Blueprint("article", __name__)


@article_bp.route("/articles", methods=["GET"])
def list_articles():
    """
    Query param:
      - category (wajib): feeding | sleep | diaper | growth | vaccination | health | mood | milestone
      - age_months (opsional): kalau diisi, artikel yang punya rentang usia
        akan difilter biar cuma yang relevan buat usia itu yang muncul.
        Artikel tanpa rentang usia (min/max null) selalu muncul di kategori manapun.
    """
    category = request.args.get("category")
    if not category:
        return jsonify({"error": "category wajib diisi"}), 400

    age_months = request.args.get("age_months", type=float)

    query = Article.query.filter_by(category=category)
    articles = query.order_by(Article.order_index.asc()).all()

    if age_months is not None:
        filtered = []
        for a in articles:
            if a.min_age_months is not None and age_months < a.min_age_months:
                continue
            if a.max_age_months is not None and age_months > a.max_age_months:
                continue
            filtered.append(a)
        articles = filtered

    return jsonify([a.to_dict() for a in articles])