(() => {
    document.querySelectorAll("[data-historical-attachments]").forEach((section) => {
        const total = section.querySelector('[name="attachments-TOTAL_FORMS"]');
        const rows = section.querySelector("[data-attachment-rows]");
        const template = section.querySelector("[data-attachment-template]");
        const add = section.querySelector("[data-add-attachment]");
        const limit = section.querySelector("[data-attachment-limit]");
        if (!total || !rows || !template || !add) return;
        const updateLimit = () => {
            const reached = Number(total.value) >= Number(section.dataset.maxForms);
            add.disabled = reached;
            if (limit) limit.hidden = !reached;
        };
        add.addEventListener("click", () => {
            const index = Number(total.value);
            if (index >= Number(section.dataset.maxForms)) return;
            const fragment = template.content.cloneNode(true);
            fragment.querySelectorAll("[name], [id], [for], [aria-describedby]").forEach((element) => {
                ["name", "id", "for", "aria-describedby"].forEach((attribute) => {
                    if (element.hasAttribute(attribute)) {
                        element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
                    }
                });
            });
            rows.append(fragment);
            total.value = index + 1;
            updateLimit();
            rows.lastElementChild?.querySelector("input, select")?.focus();
        });
        updateLimit();
    });

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

    document.querySelectorAll("[data-location-filters]").forEach((form) => {
        const department = form.querySelector('[name="department"]');
        const district = form.querySelector('[name="district"]');
        const municipality = form.querySelector('[name="municipality"]');
        department?.addEventListener("change", () => {
            if (district) district.value = "";
            if (municipality) municipality.value = "";
        });
    });

    document.querySelectorAll("form[data-auto-submit-filters]").forEach((form) => {
        let submitTimer = null;
        let isSubmitting = false;

        const submitFilters = (delay = 0) => {
            if (isSubmitting) return;
            window.clearTimeout(submitTimer);
            submitTimer = window.setTimeout(() => {
                if (form.checkValidity()) form.requestSubmit();
            }, delay);
        };

        form.querySelectorAll("select, input[type='checkbox'], input[type='radio']")
            .forEach((control) => {
                control.addEventListener("change", () => submitFilters(80));
            });
        form.querySelectorAll("input[type='search'], input[type='text']")
            .forEach((control) => {
                control.addEventListener("input", () => submitFilters(500));
            });
        form.addEventListener("submit", () => {
            isSubmitting = true;
            window.clearTimeout(submitTimer);
        });
    });

    const analysisForm = document.querySelector(".territorial-filter[data-analysis-mode]");
    const periodFilter = analysisForm?.querySelector("[data-period-filter]");
    const periodOptions = periodFilter
        ? Array.from(periodFilter.querySelectorAll('input[name="period"]'))
        : [];
    const customPeriodDates = periodFilter?.querySelector("[data-custom-period-dates]");
    const periodStart = periodFilter?.querySelector("#start");
    const periodEnd = periodFilter?.querySelector("#end");
    const periodSummary = periodFilter?.querySelector("[data-period-summary]");
    const periodError = periodFilter?.querySelector("[data-period-error]");
    const periodServerError = periodFilter?.querySelector(".period-server-error");
    const analysisUpdateStatus = analysisForm?.querySelector(
        "[data-analysis-update-status]"
    );
    const analysisSelects = analysisForm
        ? Array.from(analysisForm.querySelectorAll("select"))
        : [];
    const departmentFilter = analysisForm?.querySelector("#department");
    const districtFilter = analysisForm?.querySelector("#district");
    const advancedAnalysisFilters = analysisForm?.querySelector(
        ".territorial-advanced-filters"
    );
    const analysisStateKey = "director-analysis-filter-state";
    let analysisSubmitTimer = null;
    let analysisIsSubmitting = false;
    let analysisPeriodIsValid = true;

    const formatPeriodDate = (value) => {
        if (!value) return "";
        const [year, month, day] = value.split("-");
        return `${day}/${month}/${year}`;
    };

    const updatePeriodFilter = ({ userInteraction = false } = {}) => {
        if (
            !analysisForm ||
            !periodFilter ||
            !customPeriodDates ||
            !periodStart ||
            !periodEnd ||
            !periodSummary ||
            !periodError
        ) return;

        const selectedPeriod = periodOptions.find((option) => option.checked);
        if (!selectedPeriod) return;

        const isActivityMode = analysisForm.dataset.analysisMode === "activity";
        const isCustomPeriod = selectedPeriod.value === "custom";
        customPeriodDates.hidden = !isCustomPeriod;
        periodStart.disabled = !isCustomPeriod;
        periodEnd.disabled = !isCustomPeriod;
        periodStart.required = isActivityMode && isCustomPeriod;
        periodEnd.required = isActivityMode && isCustomPeriod;

        let errorMessage = "";
        if (isCustomPeriod && (!periodStart.value || !periodEnd.value)) {
            errorMessage = "Indica una fecha inicial y una fecha final.";
            periodSummary.textContent = "Completa las dos fechas para aplicar el rango.";
        } else if (isCustomPeriod && periodStart.value > periodEnd.value) {
            errorMessage = "La fecha inicial no puede ser posterior a la fecha final.";
            periodSummary.textContent = "Corrige el orden de las fechas para continuar.";
        } else if (isCustomPeriod) {
            periodSummary.textContent = `Mostrando actividad del ${formatPeriodDate(periodStart.value)} al ${formatPeriodDate(periodEnd.value)}`;
        } else if (selectedPeriod.value === "all") {
            periodSummary.textContent = "Mostrando actividad de todo el historial";
        } else {
            periodSummary.textContent = `Mostrando actividad: ${selectedPeriod.dataset.periodLabel}`;
        }

        periodError.textContent = errorMessage;
        periodError.hidden =
            !errorMessage || (!userInteraction && Boolean(periodServerError));
        periodStart.setAttribute("aria-invalid", String(Boolean(errorMessage)));
        periodEnd.setAttribute("aria-invalid", String(Boolean(errorMessage)));
        analysisPeriodIsValid = !isActivityMode || !errorMessage;
        if (userInteraction && periodServerError) periodServerError.hidden = true;
    };

    const persistAnalysisState = () => {
        if (!analysisForm) return;
        try {
            sessionStorage.setItem(
                analysisStateKey,
                JSON.stringify({
                    path: window.location.pathname,
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    focusId: document.activeElement?.id || "",
                    advancedOpen: Boolean(advancedAnalysisFilters?.open),
                })
            );
        } catch (_error) {
            // The filters still work if session storage is unavailable.
        }
    };

    const showAnalysisUpdate = () => {
        if (!analysisForm || !analysisUpdateStatus) return;
        analysisForm.classList.add("is-updating");
        analysisForm.setAttribute("aria-busy", "true");
        analysisUpdateStatus.hidden = false;
    };

    const submitAnalysisFilters = (delay = 0) => {
        if (!analysisForm || analysisIsSubmitting) return;
        window.clearTimeout(analysisSubmitTimer);
        analysisSubmitTimer = window.setTimeout(() => {
            if (!analysisPeriodIsValid || !analysisForm.checkValidity()) return;
            analysisForm.requestSubmit();
        }, delay);
    };

    const restoreAnalysisState = () => {
        if (!analysisForm) return;
        let savedState = null;
        try {
            savedState = JSON.parse(sessionStorage.getItem(analysisStateKey));
            sessionStorage.removeItem(analysisStateKey);
        } catch (_error) {
            return;
        }
        if (!savedState || savedState.path !== window.location.pathname) return;
        if (advancedAnalysisFilters && savedState.advancedOpen) {
            advancedAnalysisFilters.open = true;
        }
        window.requestAnimationFrame(() => {
            window.scrollTo(savedState.scrollX || 0, savedState.scrollY || 0);
            if (savedState.focusId) {
                document.getElementById(savedState.focusId)?.focus({ preventScroll: true });
            }
        });
    };

    periodOptions.forEach((option) => {
        option.addEventListener("change", () => {
            updatePeriodFilter({ userInteraction: true });
            if (option.value !== "custom") submitAnalysisFilters(80);
        });
    });
    [periodStart, periodEnd].forEach((dateField) => {
        dateField?.addEventListener("input", () => {
            updatePeriodFilter({ userInteraction: true });
            if (periodError?.hidden) submitAnalysisFilters(450);
        });
    });
    analysisSelects.forEach((select) => {
        select.addEventListener("change", () => {
            if (select === departmentFilter) {
                if (districtFilter) districtFilter.value = "";
            }
            submitAnalysisFilters(80);
        });
    });
    analysisForm?.addEventListener("submit", () => {
        analysisIsSubmitting = true;
        persistAnalysisState();
        showAnalysisUpdate();
    });
    document.querySelectorAll(".analysis-mode-switch a").forEach((link) => {
        link.addEventListener("click", () => {
            persistAnalysisState();
            showAnalysisUpdate();
        });
    });
    updatePeriodFilter();
    restoreAnalysisState();
})();

document.querySelectorAll("[data-select-page]").forEach((toggle) => {
    const group = toggle.dataset.selectPage;
    const items = Array.from(document.querySelectorAll(`[data-selection-item="${group}"]`));
    const refresh = () => {
        const checked = items.filter((item) => item.checked).length;
        toggle.checked = items.length > 0 && checked === items.length;
        toggle.indeterminate = checked > 0 && checked < items.length;
    };
    toggle.addEventListener("change", () => {
        items.forEach((item) => { item.checked = toggle.checked; });
        refresh();
    });
    items.forEach((item) => item.addEventListener("change", refresh));
    refresh();
});
