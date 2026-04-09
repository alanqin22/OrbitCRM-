<?php
/**
 * Contact Form Handler — Agentorc.ca
 * Accepts POST from the contact form and emails the submission to the site owner.
 */

header('Content-Type: application/json');

/* ── Only accept POST ── */
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['ok' => false, 'error' => 'Method not allowed']);
    exit;
}

/* ── Sanitize helper ── */
function clean(string $val): string {
    return htmlspecialchars(strip_tags(trim($val)), ENT_QUOTES, 'UTF-8');
}

/* ── Collect and sanitize fields ── */
$company = clean($_POST['company'] ?? '');
$name    = clean($_POST['name']    ?? '');
$phone   = clean($_POST['phone']   ?? '');
$email   = trim($_POST['email']    ?? '');
$message = clean($_POST['message'] ?? '');

/* ── Server-side validation ── */
if (!$name) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Name is required.']);
    exit;
}
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'A valid email address is required.']);
    exit;
}
if (!$message) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Message is required.']);
    exit;
}

/* ── Destination ── */
$to      = 'alanqin@agentorc.ca';
$subject = 'New Contact Message — Agentorc.ca';

/* ── Plain-text body ── */
$bodyText  = "New contact message from Agentorc.ca\n";
$bodyText .= str_repeat('-', 44) . "\n";
if ($company) $bodyText .= "Company : {$company}\n";
$bodyText .= "Name    : {$name}\n";
if ($phone)   $bodyText .= "Phone   : {$phone}\n";
$bodyText .= "Email   : {$email}\n";
$bodyText .= str_repeat('-', 44) . "\n";
$bodyText .= "Message :\n{$message}\n";

/* ── HTML body ── */
$emailDisplay = htmlspecialchars($email, ENT_QUOTES, 'UTF-8');
$rows = '';
if ($company) $rows .= row('Company', $company);
$rows .= row('Name',  $name);
if ($phone)   $rows .= row('Phone',  $phone);
$rows .= '<tr>
    <td style="padding:8px 12px 8px 0;color:#555;font-weight:600;white-space:nowrap;vertical-align:top;">Email</td>
    <td style="padding:8px 0;"><a href="mailto:' . $emailDisplay . '" style="color:#7c3aed;">' . $emailDisplay . '</a></td>
  </tr>';

function row(string $label, string $value): string {
    return '<tr>
    <td style="padding:8px 12px 8px 0;color:#555;font-weight:600;white-space:nowrap;vertical-align:top;">' . $label . '</td>
    <td style="padding:8px 0;">' . $value . '</td>
  </tr>';
}

$bodyHtml = '<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:\'Segoe UI\',Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.10);">
    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1c2e4a 0%,#3b1d6e 100%);padding:28px 32px;">
      <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.01em;">
        Agentorc.ca
      </p>
      <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.65);">
        New Contact Message
      </p>
    </div>
    <!-- Body -->
    <div style="padding:28px 32px;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.6;">
        ' . $rows . '
      </table>
      <!-- Message block -->
      <div style="margin-top:20px;padding:18px 20px;background:#f8f6ff;border-left:4px solid #7c3aed;border-radius:4px;">
        <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:0.06em;">Message</p>
        <p style="margin:0;font-size:14px;line-height:1.75;color:#1a1a2e;white-space:pre-wrap;">' . nl2br($message) . '</p>
      </div>
    </div>
    <!-- Footer -->
    <div style="padding:16px 32px;background:#f4f4f8;border-top:1px solid #e8e8f0;">
      <p style="margin:0;font-size:12px;color:#999;">
        Sent from the Agentorc.ca contact form &nbsp;·&nbsp; Reply directly to this email to respond to ' . $name . '.
      </p>
    </div>
  </div>
</body>
</html>';

/* ── Build multipart MIME message ── */
$boundary = '----=_Part_' . md5(uniqid('', true));

$headers  = "MIME-Version: 1.0\r\n";
$headers .= "Content-Type: multipart/alternative; boundary=\"{$boundary}\"\r\n";
$headers .= "From: Agentorc.ca <noreply@agentorc.ca>\r\n";
$headers .= "Reply-To: {$name} <{$email}>\r\n";
$headers .= "X-Mailer: PHP/" . PHP_VERSION . "\r\n";

$body  = "--{$boundary}\r\n";
$body .= "Content-Type: text/plain; charset=UTF-8\r\n";
$body .= "Content-Transfer-Encoding: base64\r\n\r\n";
$body .= chunk_split(base64_encode($bodyText)) . "\r\n";

$body .= "--{$boundary}\r\n";
$body .= "Content-Type: text/html; charset=UTF-8\r\n";
$body .= "Content-Transfer-Encoding: base64\r\n\r\n";
$body .= chunk_split(base64_encode($bodyHtml)) . "\r\n";

$body .= "--{$boundary}--";

/* ── Send ── */
$sender = 'noreply@agentorc.ca';
$sent   = mail($to, $subject, $body, $headers, "-f " . $sender);

/* ── Log result ── */
$logFile = __DIR__ . '/mail_debug.log';
$timestamp = date('Y-m-d H:i:s');
$status = $sent ? 'SUCCESS' : 'FAILED';
$logEntry = "[$timestamp] [{$status}] To: $to | From: $email | Name: $name\n";
if (!$sent) {
    $errorMsg = error_get_last()['message'] ?? 'Unknown error';
    $logEntry .= "    Error: $errorMsg\n";
}
file_put_contents($logFile, $logEntry, FILE_APPEND);

if ($sent) {
    echo json_encode(['ok' => true]);
} else {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'The mail server could not send the message. Please try again or email us directly at alanqin@agentorc.ca']);
}
