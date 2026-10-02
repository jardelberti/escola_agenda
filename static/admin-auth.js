// Enrollment secrets stay in the fragment, never in web-server URLs or referrers.
const accessField = document.getElementById('access_token');
if (accessField) {
    const token = location.hash.slice(1);
    if (token) {
        accessField.value = token;
        history.replaceState(null, '', location.pathname);
    }
    const missing = document.getElementById('missing-link');
    const submit = document.getElementById('set-password-button');
    missing.hidden = Boolean(accessField.value);
    submit.disabled = !accessField.value;
}
