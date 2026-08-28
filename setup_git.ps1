# Run this once from the resilient-model-gateway directory to initialize git.

git init
git branch -m master main 2>$null
git add .
git commit -m "Initial commit: resilient model gateway scaffold"

Write-Host ""
Write-Host "Done! To push to GitHub (create the repo on github.com first):"
Write-Host "  git remote add origin https://github.com/jpei33/resilient-model-gateway.git"
Write-Host "  git push -u origin main"
