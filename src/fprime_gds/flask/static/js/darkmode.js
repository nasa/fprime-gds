let darkMode = localStorage.getItem("enableDarkGDS") == "true";

function toggleDarkmode() {
    document.body.classList.toggle("fprime-darkmode");
    document.body.classList.toggle("fpstyle-darkmode");
    darkMode = !darkMode;
    localStorage.setItem("enableDarkGDS", darkMode);
}

window.onload = function() {
    if(darkMode) {
        document.getElementById("theme-checkbox").click();
        darkMode = !darkMode;
        localStorage.setItem("enableDarkGDS", darkMode);
    }
}
