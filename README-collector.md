# Image collector add-on

This add-on collects candidate image/link pairs from configured search pages and writes local images into:

```text
images/collected/
```

## Files

```text
sources.json
requirements.txt
scripts/collect.py
.github/workflows/collect.yml
```

## GitHub setup

1. Upload these files with the same folder structure.
2. Open **Settings → Actions → General**.
3. In **Workflow permissions**, choose **Read and write permissions**.
4. Open the **Actions** tab.
5. Select **Collect style images**.
6. Press **Run workflow**.

The workflow also runs weekly.

## Important note

If the site is public, downloaded third-party images may be publicly visible.
Use this only for personal curation and be mindful of source site terms and image rights.
