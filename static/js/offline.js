// Página «Sin conexión» (templates/offline.html). El service worker la muestra en la
// dirección que no se pudo abrir, así que location es la página que la persona pidió.
(() => {
    const SECRET_PATH = /^\/(activar-cuenta|restablecer)\/.+$/;
    const fill = (selector, text) => {
        const element = document.querySelector(selector);
        if (element) element.textContent = text;
    };
    const pad = (value) => String(value).padStart(2, "0");
    const now = new Date();
    fill("[data-offline-time]", `${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
    fill("[data-offline-path]", `GET ${window.location.pathname.replace(SECRET_PATH, "/$1/[oculto]/")}`);

    const showNetwork = () => {
        fill("[data-offline-network]", navigator.onLine ? "Conectada" : "Sin red");
        fill("[data-offline-status]", navigator.onLine
            ? "El dispositivo tiene red, pero el servidor no respondió."
            : "El dispositivo no tiene conexión a internet en este momento.");
    };
    showNetwork();
    window.addEventListener("offline", showNetwork);
    window.addEventListener("online", () => {
        showNetwork();
        window.location.reload();
    });
    document.querySelector("[data-offline-retry]")?.addEventListener("click", () => window.location.reload());
})();
