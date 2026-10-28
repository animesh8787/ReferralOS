"""Background task handlers for the profile: resume parsing, GitHub import, portfolio import."""
from ..adapters import github_api
from ..adapters.http import FetchError, PoliteFetcher, make_client
from ..models.profile import ProfileItem, Resume
from ..tasks import handler
from . import portfolio, profile, resume_parse
from .. import storage


@handler("parse_resume")
def parse_resume(ctx):
    r = ctx.db.query(Resume).filter(Resume.id == ctx.payload["resume_id"]).one()
    try:
        text, info = resume_parse.extract_text(storage.get(r.user_id, "resumes", r.id, f".{r.ext}"), r.filename)
    except resume_parse.ParseError as e:  # not retryable: record and finish
        r.status, r.parse_info = "failed", {"error": str(e)}
        return {"error": str(e)}
    r.raw_text, r.parse_info = text, info
    if info["image_only"]:
        r.status = "image_only"
        return {"warning": info["warnings"][0]}
    items, report = resume_parse.structure(text)
    r.status, r.parse_info = "parsed", {**info, **report}
    ctx.update(progress=0.7)
    # a re-upload replaces what earlier resume imports added and the user has not confirmed or edited (edits become source "manual")
    ctx.db.query(ProfileItem).filter(ProfileItem.source == "resume", ProfileItem.verified.is_(False),
                                     ProfileItem.status.in_(("active", "suggested"))).delete(synchronize_session=False)
    res = profile.add_parsed(ctx.db, items, "resume", r.id)
    profile.snapshot(ctx.db, f"Imported resume {r.filename}")
    return {**res, "rejected": len(report["rejected"])}


@handler("github_import")
def github_import(ctx):
    user = ctx.payload["username"]
    from ..models.core import UserSetting
    from .. import crypto
    row = ctx.db.query(UserSetting).filter(UserSetting.key == "github.token").first()
    gh = github_api.GitHubClient(make_client(), crypto.decrypt(row.value["enc"]) if row and row.value.get("enc") else None)
    try:
        repos = gh.repos(user)
        readmes = {}
        for i, r in enumerate(repos[:30]):  # cap README fetches to stay within unauthenticated limits
            readmes[r["full_name"]] = gh.readme(r["full_name"])
            ctx.update(progress=0.1 + 0.8 * i / max(1, min(30, len(repos))))
    except github_api.NotFound:
        return {"error": f"GitHub user '{user}' was not found"}
    except github_api.RateLimited as e:
        return {"error": str(e)}  # surfaced to the user; they retry later
    res = profile.add_parsed(ctx.db, github_api.to_items(repos, readmes), "github", f"github:{user}",
                             status="suggested", confidence_cap=0.5)
    return {**res, "repos": len(repos)}


@handler("portfolio_import")
def portfolio_import(ctx):
    url = ctx.payload["url"]
    f = PoliteFetcher()
    try:
        r = f.get(url)
    except FetchError as e:
        return {"error": str(e)}
    if r.status_code >= 400:
        return {"error": f"The page returned HTTP {r.status_code}"}
    items = portfolio.to_items(portfolio.parse_html(r.text, url))
    res = profile.add_parsed(ctx.db, items, "portfolio", url, status="suggested", confidence_cap=0.4)
    return res
