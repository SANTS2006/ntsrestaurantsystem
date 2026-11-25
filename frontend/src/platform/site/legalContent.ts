// Draft legal templates with placeholders. NOT legal advice; review before publication.
type Doc = Array<[string, string]>
const C = '[Company Name]'

export const legalDocs: Record<string, Doc> = {
  'privacy-policy': [
    ['Who we are', `${C} operates a restaurant management platform. This policy explains how personal data is handled. [Registered address and contact details]`],
    ['Data we collect', 'Account details (name, email, phone), order and payment records, delivery addresses, and technical data such as IP address and device information used for security.'],
    ['How we use data', 'To provide the service, process orders and payments, send transactional emails, prevent fraud and abuse, and meet legal obligations.'],
    ['Sharing', 'Data is shared with the restaurant you order from and with service providers (for example email and payment providers) acting on our instructions. [List providers]'],
    ['Retention and your rights', 'Financial records are retained as required by law. Contact us to request access, correction or deletion where applicable. [Describe the process and timelines]'],
  ],
  'terms-of-service': [
    ['Acceptance', `By creating an account you agree to these terms with ${C}. [Version and effective date]`],
    ['Accounts', 'You are responsible for keeping your credentials confidential and for activity under your account.'],
    ['Acceptable use', 'You must not misuse the service, attempt to access other accounts or tenants, or interfere with its operation.'],
    ['Availability and liability', '[Describe service levels, limitations of liability and governing law.]'],
    ['Changes', 'We may update these terms; material changes will be notified and a new version recorded.'],
  ],
  'payment-terms': [
    ['Payments', 'Orders may be paid in cash, by mobile money or through supported online providers. Payment is confirmed only when the provider or cashier confirms it.'],
    ['Fees and taxes', '[State platform fees, restaurant prices, taxes and delivery fees.]'],
    ['Disputes', '[Explain how payment disputes are raised and resolved.]'],
  ],
  'refund-and-cancellation-policy': [
    ['Cancellations', '[State when an order can be cancelled and by whom.]'],
    ['Refunds', '[State eligibility, method, timelines and approval process for refunds.]'],
    ['Subscriptions', '[State cancellation and refund terms for platform subscriptions.]'],
  ],
  'cookie-policy': [
    ['Cookies and storage', 'We use essential storage to keep you signed in and remember preferences. [List any analytics or marketing cookies and the consent mechanism.]'],
    ['Managing preferences', '[Explain how users can change their choices.]'],
  ],
  'security-policy': [
    ['Our approach', 'Access is checked on the server for every request. Each restaurant’s data is isolated, passwords are stored as salted hashes, sign-in attempts are rate limited, and sensitive actions are audit logged.'],
    ['Reporting a vulnerability', '[Provide a security contact and disclosure process.]'],
    ['Limits of this page', 'Do not rely on this summary as an assurance of any certification. [Add only certifications you actually hold.]'],
  ],
  'acceptable-use-policy': [
    ['Prohibited activity', 'Unauthorised access attempts, scraping, spam, fraudulent orders or payments, uploading unlawful or malicious content, and attempts to disrupt the service.'],
    ['Enforcement', '[Describe warnings, suspension and termination.]'],
  ],
}
