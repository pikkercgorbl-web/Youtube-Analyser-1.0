# Read-only HTTP smoke for key UI routes (requires frontend on :3000).
$routes = @("/opportunities", "/saved-topics", "/validation")
foreach ($route in $routes) {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000$route" -UseBasicParsing -TimeoutSec 20
    Write-Output "$route -> $($resp.StatusCode)"
  } catch {
    Write-Output "$route -> FAIL"
  }
}
