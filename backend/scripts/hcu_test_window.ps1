param([string]$OutFile)
# Harmless HCU test target: a native WinForms window with one TextBox.
# Mirrors the TextBox value to $OutFile; closes when "$OutFile.close" exists or after 40 s.
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.Text = "FLAssistant HCU Test Window"
$form.Width = 440; $form.Height = 140
$form.StartPosition = "Manual"; $form.Left = 60; $form.Top = 60
$tb = New-Object System.Windows.Forms.TextBox
$tb.Name = "pocInput"; $tb.AccessibleName = "PoC Input"
$tb.Left = 20; $tb.Top = 30; $tb.Width = 380
$form.Controls.Add($tb)
$deadline = (Get-Date).AddSeconds(40)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100
$timer.Add_Tick({
    Set-Content -LiteralPath $OutFile -Value $tb.Text -NoNewline -Encoding UTF8
    if ((Test-Path -LiteralPath "$OutFile.close") -or ((Get-Date) -gt $deadline)) { $form.Close() }
})
$timer.Start()
[void]$form.ShowDialog()

