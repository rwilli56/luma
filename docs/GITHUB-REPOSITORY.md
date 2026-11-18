# Install and update from GitHub

Luma includes a real Kodi repository builder and a GitHub Pages deployment workflow. The repository metadata uses Kodi's required `<dir>` structure and serves both the video add-on and the repository add-on, so Kodi can update either.

**Published repository:** [rwilli56/luma](https://github.com/rwilli56/luma)

**Live Kodi source:** [https://rwilli56.github.io/luma/](https://rwilli56.github.io/luma/)

**Bootstrap package:** [repository.luma-0.1.1.zip](https://rwilli56.github.io/luma/repository.luma-0.1.1.zip)

The initial publishing run passed the 55 automated tests and deployed the repository to GitHub Pages. Hardware and live account validation remains pending. The instructions below also explain how to maintain or fork the distribution.

## Publish

1. Create a GitHub repository for this project, or use the intended existing repository. A public repository is the straightforward choice for public Kodi installation.
2. Push this project to its `main` or `master` branch. Commit generated skin XML and PNG assets: the publishing workflow has no Pillow dependency.
3. In GitHub **Settings → Pages → Build and deployment → Source**, select **GitHub Actions**.
4. Run **Actions → Publish Kodi repository → Run workflow**. Future pushes changing runtime source, packaging or tests trigger the same workflow.
5. Use the deployed URL reported by the workflow, typically `https://OWNER.github.io/REPOSITORY/`. The workflow obtains the exact URL from GitHub's configure-pages action, so repository names and custom Pages domains do not require editing the add-on template.

No account keys or API tokens belong in GitHub. TorBox, Trakt and Emby credentials are entered on the Kodi device.

## Install on Kodi

1. **Settings → File manager → Add source**: enter the deployed Pages URL and name it `Luma`.
2. Enable installation from unknown sources in Kodi's add-on settings if needed.
3. **Add-ons → Install from zip file → Luma → repository.luma-0.1.1.zip**.
4. **Install from repository → Luma Repository → Video add-ons → Luma → Install**.
5. Open Luma and connect TorBox. Kodi's normal add-on update preferences govern later updates.

You can also download the repository ZIP from the Pages site in a browser and transfer it to Kodi. GitHub's green **Code → Download ZIP** downloads project source and is not the installable Kodi package.

## Build locally

```powershell
python tools/build_repository.py --base-url https://OWNER.github.io/REPOSITORY
```

The example above must use your actual published address. Upload the complete contents of `dist/repository/` to that HTTPS base URL. Output includes:

```text
index.html
addons.xml
addons.xml.md5
repository.luma-0.1.1.zip
repository.luma/
  repository.luma-0.1.1.zip
  repository.luma-0.1.1.zip.sha256
  icon.png
plugin.video.luma/
  plugin.video.luma-0.3.0.zip
  plugin.video.luma-0.3.0.zip.sha256
  resources/...
```

The source `repository.luma/addon.xml.in` is a template. Only the builder's ZIP has final URLs. The builder rejects non-HTTPS base URLs, embedded credentials, queries and fragments. `addons.xml.md5` is Kodi's index change detector; each ZIP also gets a SHA-256 file. The repository does not request nonstandard hash headers that GitHub Pages does not supply.

## If Kodi cannot connect to the repository

Repository 0.1.1 adds an explicit `xbmc.addon` dependency and removes the directory's internal API-version gate. Install this ZIP manually over repository 0.1.0, since a repository that cannot refresh cannot discover its own update. Then long-press **Luma Repository → Check for updates** and reopen it.

The original download page omitted the `addons.xml.md5` link. Kodi's HTTP directory cache can then treat this real file as nonexistent after you browse the source to install the ZIP. Kodi also requires a directory link's visible label to match its filename. The site now lists both the catalog and checksum using their actual filenames. **Fully exit and restart Kodi, then open Luma Repository directly** to clear the old in-memory directory listing; another repository ZIP reinstall is not needed for this site fix.

The live verifier now checks the HTML listing as well as direct downloads and hashes. This reflects Kodi's [file-open check](https://github.com/xbmc/xbmc/blob/Omega/xbmc/filesystem/File.cpp) and [directory-cache lookup](https://github.com/xbmc/xbmc/blob/Omega/xbmc/filesystem/DirectoryCache.cpp). If the error continues after restart, check recent log entries for `repository.luma`, `CRepository`, `CCurlFile`, or `AddonsFromRepoXML`.

Before an update, bump the affected add-on's version in `plugin.video.luma/addon.xml` or `repository.luma/addon.xml.in`. Do not replace a published version with different code: Kodi's version comparison controls update discovery. This first workflow publishes the current version only; archived releases are not retained across clean CI builds.

Repository mechanics follow [Kodi's repository documentation](https://kodi.wiki/view/Add-on_repositories). Deployment follows [GitHub's custom Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
