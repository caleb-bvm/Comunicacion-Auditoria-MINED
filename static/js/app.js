(() => {
    const moreTrigger = document.querySelector(".mobile-more-trigger");
    const moreMenu = document.querySelector(".mobile-more-menu");
    const moreScrim = document.querySelector(".mobile-more-scrim");
    const moreClose = document.querySelector(".mobile-more-close");

    const setMoreMenu = (open) => {
        if (!moreTrigger || !moreMenu || !moreScrim) return;
        moreTrigger.setAttribute("aria-expanded", String(open));
        moreMenu.hidden = !open;
        moreScrim.hidden = !open;
        document.body.classList.toggle("has-open-mobile-menu", open);
        if (open) moreClose?.focus();
        else moreTrigger.focus();
    };

    moreTrigger?.addEventListener("click", () => {
        setMoreMenu(moreTrigger.getAttribute("aria-expanded") !== "true");
    });
    moreClose?.addEventListener("click", () => setMoreMenu(false));
    moreScrim?.addEventListener("click", () => setMoreMenu(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && moreTrigger?.getAttribute("aria-expanded") === "true") {
            setMoreMenu(false);
        }
    });

    const statusField = document.querySelector("#id_declared_status");
    const conditionalFields = document.querySelectorAll("[data-visible-for-status]");
    const updateResponseFields = () => {
        if (!statusField || !conditionalFields.length) return;
        conditionalFields.forEach((field) => {
            const visibleFor = (field.dataset.visibleForStatus || "").split(" ");
            const visible = visibleFor.includes(statusField.value);
            field.hidden = !visible;
            field.querySelectorAll("input, select, textarea").forEach((control) => {
                control.disabled = !visible;
            });
        });
    };
    statusField?.addEventListener("change", updateResponseFields);
    updateResponseFields();
})();
