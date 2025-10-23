# ================================
# build_lambda.ps1
# ================================

Write-Host "🚀 Building AWS Lambda package..." -ForegroundColor Green

# Clean up old builds
if (Test-Path lambda-package) { 
    Remove-Item -Recurse -Force lambda-package 
    Write-Host "🧹 Old build folder removed."
}
if (Test-Path lambda-function.zip) { 
    Remove-Item -Force lambda-function.zip 
    Write-Host "🧹 Old ZIP file removed."
}

# Create package directory
New-Item -ItemType Directory -Path lambda-package | Out-Null
Set-Location lambda-package

# Install dependencies
Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
pip install -r ..\requirements.txt -t . --quiet

# Download spaCy model
Write-Host "🧠 Downloading spaCy model..." -ForegroundColor Yellow
python -m spacy download en_core_web_sm --quiet

# Copy source files
Write-Host "📁 Copying project files..." -ForegroundColor Yellow
Copy-Item ..\main.py .
Copy-Item ..\live_fill_final.py .

# (No need to copy JSONs — they’re loaded from S3 at runtime)

# Create ZIP
Write-Host "📦 Creating deployment ZIP..." -ForegroundColor Yellow
Compress-Archive -Path * -DestinationPath ..\lambda-function.zip -Force

# Return to root
Set-Location ..

# Show size
$size = (Get-Item lambda-function.zip).Length / 1MB
Write-Host ("✅ Done! Package size: {0} MB" -f [math]::Round($size, 2)) -ForegroundColor Green
Write-Host "📦 File: lambda-function.zip"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1️⃣ Go to AWS Lambda Console"
Write-Host "2️⃣ Create a new function (Python 3.12 runtime)"
Write-Host "3️⃣ Upload lambda-function.zip under 'Code > Upload from > .zip file'"
Write-Host "4️⃣ Set Handler to: main.lambda_handler"
Write-Host "5️⃣ Set Timeout to 60 seconds and Memory to 512+ MB"
Write-Host "6️⃣ Add Environment Variables:"
Write-Host "     OPENAI_API_KEY = your_api_key"
Write-Host "     AWS_REGION = your_region"
Write-Host "7️⃣ Save & Test your function 🚀"
