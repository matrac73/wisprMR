# Deploiement Vercel

Le site est deploye depuis le dossier `website/`.

## Production actuelle

- URL production : `https://website-eight-ashen-98.vercel.app`
- Projet Vercel : `matrac73s-projects/website`
- Root directory : `website`
- Framework preset : `Other`
- Build command : vide
- Output directory : `.`

## Deploiement automatique GitHub

Le workflow `.github/workflows/vercel-production.yml` redeploie en production a chaque push sur `main` ou `master` si des fichiers `website/**` changent.

Dans GitHub, ajoute ces secrets au repo :

- `VERCEL_TOKEN` : token Vercel avec acces deploy.
- `VERCEL_ORG_ID` : `team_reIsiAyrDVlB4XtLsIoUPHc1`
- `VERCEL_PROJECT_ID` : `prj_CeEzmpDwseqwdHWDs1fjAISx5gwy`

Chemin GitHub :

```text
Settings > Secrets and variables > Actions > New repository secret
```

## Deploiement manuel

Depuis `website/` :

```bash
npx vercel@latest deploy --prod
```

## Fichiers de telechargement

- `website/downloads/WisprMR-Setup.exe`
- `website/downloads/WisprMR-Install.zip`
