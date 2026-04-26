# Share Site

This folder is a deployment-ready static site.

## Files

- `index.html`: the shareable page to host
- `custom-report-data.json`: the embedded source data in JSON form
- `.nojekyll`: keeps GitHub Pages from rewriting the site

## Fastest ways to share

### GitHub Pages

1. Create a new GitHub repository.
2. Upload everything in this folder to the repository root.
3. In GitHub, open `Settings` -> `Pages`.
4. Set the source to `Deploy from a branch`, pick `main`, and save.

### Netlify

1. Open Netlify.
2. Drag this whole folder into the deploy area.
3. Netlify will publish it as a static site immediately.

### Local preview

Run this inside the folder:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`.
