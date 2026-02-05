# Configuration
$PythonVersion = "3.11.9"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PipUrl = "https://bootstrap.pypa.io/get-pip.py"
$BaseDir = $PSScriptRoot
$PythonDir = Join-Path $BaseDir "python_bin"
$PythonExe = Join-Path $PythonDir "python.exe"
$PipExe = Join-Path $PythonDir "Scripts\pip.exe"

# Corporate Proxy/SSL Bypass Flags
$TrustedHosts = @("--trusted-host", "pypi.org", "--trusted-host", "pypi.python.org", "--trusted-host", "files.pythonhosted.org")

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   PYTHON ENVIRONMENT SETUP" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Working Directory: $BaseDir" -ForegroundColor Gray
Write-Host ""

# [1/5] Checking Python environment
Write-Host "[1/5] Checking Python environment..." -ForegroundColor Yellow

if (Test-Path $PythonExe) {
    Write-Host "      Portable Python is already present." -ForegroundColor Green
} else {
    Write-Host "      Downloading Portable Python ($PythonVersion)..." -ForegroundColor Cyan
    try {
        # Create directory
        New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
        
        # Download Zip
        $ZipPath = Join-Path $BaseDir "python.zip"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $PythonUrl -OutFile $ZipPath -UseBasicParsing
        
        # Extract
        Write-Host "      Extracting..." -ForegroundColor Cyan
        Expand-Archive -Path $ZipPath -DestinationPath $PythonDir -Force
        Remove-Item $ZipPath -Force
        
        Write-Host "      Python extracted successfully." -ForegroundColor Green
    } catch {
        Write-Host "      [ERROR] Failed to download/extract Python. Check internet." -ForegroundColor Red
        Write-Host "      Error: $_" -ForegroundColor Red
        Pause
        exit
    }
}

# [2/5] Configuring Python for local imports
# CRITICAL: Fix the _pth file to allow importing site-packages (required for Pip)
Write-Host "[2/5] Configuring Python for local imports..." -ForegroundColor Yellow
$PthFile = Get-ChildItem -Path $PythonDir -Filter "*._pth" | Select-Object -First 1
if ($PthFile) {
    $Content = Get-Content $PthFile.FullName
    # Uncomment 'import site' if it's commented out
    $NewContent = $Content -replace "#import site", "import site"
    $NewContent | Set-Content $PthFile.FullName
}

# [3/5] Installing Pip package manager
Write-Host "[3/5] Installing Pip package manager..." -ForegroundColor Yellow
if (-not (Test-Path $PipExe)) {
    try {
        $GetPipPath = Join-Path $BaseDir "get-pip.py"
        Invoke-WebRequest -Uri $PipUrl -OutFile $GetPipPath -UseBasicParsing
        
        # Run get-pip.py using our portable python
        & $PythonExe $GetPipPath --no-warn-script-location $TrustedHosts
        
        Remove-Item $GetPipPath -Force
    } catch {
        Write-Host "      [WARNING] Could not auto-install pip. You might need to download get-pip.py manually." -ForegroundColor Red
    }
} else {
    Write-Host "      Pip is already installed." -ForegroundColor Green
}

# [4/5] Installing Libraries (Requests, Playwright)
Write-Host "[4/5] Installing Libraries from requirements.txt..." -ForegroundColor Yellow
if (Test-Path (Join-Path $BaseDir "requirements.txt")) {
    & $PythonExe -m pip install -r "$BaseDir\requirements.txt" --no-warn-script-location $TrustedHosts
} else {
    Write-Host "      requirements.txt not found. Skipping library installation." -ForegroundColor Gray
}

# [5/5] Setting up Playwright Browsers (Optional - remove if not using Playwright)
if (Get-Content (Join-Path $BaseDir "requirements.txt") -ErrorAction SilentlyContinue | Select-String "playwright") {
    Write-Host "[5/5] Setting up Playwright Browsers..." -ForegroundColor Yellow
    Write-Host "      (This may take a moment and download Chromium)" -ForegroundColor Gray
    & $PythonExe -m playwright install chromium
}

Write-Host ""
Write-Host "SUCCESS: Installation complete!" -ForegroundColor Green
Pause
