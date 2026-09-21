function toggleDarkmode() {
    document.body.classList.toggle("fprime-darkmode");
    document.body.classList.toggle("fpstyle-darkmode");
}

// Click the darkmode switch :)
function enableDarkmodeByDefault() {
    document.getElementById("theme-checkbox").click();
}

// Run on page load
window.onload = function() {
    enableDarkmodeByDefault();
}
