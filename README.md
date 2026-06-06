# Solid Inspiration

A quiet style board by **Canora Pats**.

This is a small GitHub Pages portal for collecting and viewing items, articles and archive inspirations aligned with:

- Dark brown / cognac / oxblood / beige
- Leather / bridle leather / brass / walnut / wool / silk
- British restraint
- Italian grand tourer elegance
- Quiet luxury
- Practical quality
- Objects that age beautifully

## Files

```text
index.html
style.css
data.json
robots.txt
.gitignore
README.md
```

## How to publish with GitHub Pages

1. Create a new public repository, for example `solid-inspiration-board`.
2. Upload all files in this folder to the repository root.
3. Open **Settings → Pages**.
4. Set:
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/root`
5. Wait a few minutes.
6. Open the URL shown by GitHub Pages.

The URL will usually look like:

```text
https://<your-github-username>.github.io/solid-inspiration-board/
```

## Search avoidance

The site includes these meta tags in `index.html`:

```html
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<meta name="googlebot" content="noindex, nofollow, noarchive, nosnippet">
<meta name="bingbot" content="noindex, nofollow, noarchive, nosnippet">
```

This makes the site harder to find in search engines, but it is not true access control.
Anyone who knows the URL may still be able to open the site.

## Editing cards

Cards are stored in `data.json`.

Each item has:

```json
{
  "title": "Example",
  "url": "https://example.com/",
  "category": "Leather & Bags",
  "score": 85,
  "description": "Short description.",
  "reason": "Why this fits the board.",
  "tags": ["dark brown", "leather"]
}
```

Use scores as an editorial fit indicator, not as an objective ranking.

## Future expansion

Possible next steps:

- Add RSS collection.
- Add YouTube channel updates.
- Add AI-based fit scoring.
- Separate items into `Available`, `Archive`, and `Inspiration`.
- Add a weekly digest page.
