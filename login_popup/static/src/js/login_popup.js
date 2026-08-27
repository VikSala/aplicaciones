/** @odoo-module **/

const LOGIN_PATH = "/web/login";
const LOGIN_POPUP_AUTH_PATH = "/login_popup/authenticate";
const SIGNUP_PATH = "/web/signup";
const RESET_PASSWORD_PATH = "/web/reset_password";

function whenReady(callback) {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", callback, { once: true });
    } else {
        callback();
    }
}

whenReady(() => {
    const overlay = document.getElementById("o_login_popup_overlay");
    const popup = document.getElementById("o_login_popup");
    const loginForm = document.getElementById("o_login_popup_form");

    if (!overlay || !popup || !loginForm) {
        return;
    }

    const views = {
        login: document.getElementById("o_login_popup_login_view"),
        "signup-choice": document.getElementById("o_login_popup_signup_choice_view"),
        particular: document.getElementById("o_login_popup_signup_particular_view"),
        professional: document.getElementById("o_login_popup_signup_professional_view"),
        "reset-password": document.getElementById("o_login_popup_reset_password_view"),
    };

    const closeButton = popup.querySelector(".o_login_popup_close");
    const loginInput = document.getElementById("o_login_popup_login");
    const loginPasswordInput = document.getElementById("o_login_popup_password");
    const loginRedirectInput = document.getElementById("o_login_popup_redirect");
    const loginErrorBox = document.getElementById("o_login_popup_error");
    const loginSubmitButton = document.getElementById("o_login_popup_submit");
    const loginSubmitText = loginSubmitButton?.querySelector(".o_login_popup_submit_text");
    const loginSpinner = loginSubmitButton?.querySelector(".o_login_popup_spinner");
    const signupForms = Array.from(popup.querySelectorAll(".o_login_popup_signup_form"));
    const professionalForm = document.getElementById("o_login_popup_signup_professional_form");
    const professionalExtraFields = document.getElementById("o_login_popup_professional_extra_fields");
    const professionalTypeInputs = Array.from(
        professionalForm?.querySelectorAll('input[name="professional_type"]') || []
    );
    const professionalVatInput = document.getElementById("o_signup_professional_vat");
    const professionalVatLabel = document.getElementById("o_signup_professional_vat_label");
    const resetForm = document.getElementById("o_login_popup_reset_form");
    const resetEmailInput = document.getElementById("o_login_popup_reset_email");
    const resetRedirectInput = popup.querySelector(".o_login_popup_reset_redirect");
    const resetErrorBox = document.getElementById("o_login_popup_reset_error");
    const resetSuccess = document.getElementById("o_login_popup_reset_success");
    const resetSuccessMessage = document.getElementById("o_login_popup_reset_success_message");
    const resetSubmitButton = document.getElementById("o_login_popup_reset_submit");
    const resetSubmitText = resetSubmitButton?.querySelector(".o_login_popup_reset_submit_text");
    const resetSpinner = resetSubmitButton?.querySelector(".o_login_popup_spinner");

    let lastFocusedElement = null;
    let closingTimer = null;
    let currentView = "login";

    const currentRelativeUrl = () =>
        `${window.location.pathname}${window.location.search}${window.location.hash}`;

    const setBoxError = (box, message = "") => {
        if (!box) {
            return;
        }
        box.textContent = message;
        box.hidden = !message;
    };

    const setLoginLoading = (loading) => {
        if (!loginSubmitButton) {
            return;
        }
        loginSubmitButton.disabled = loading;
        if (loginSubmitText) {
            loginSubmitText.textContent = loading ? "Iniciando sesión…" : "Iniciar sesión";
        }
        if (loginSpinner) {
            loginSpinner.hidden = !loading;
        }
    };

    const setSignupLoading = (form, loading) => {
        const button = form.querySelector(".o_login_popup_signup_submit");
        const text = button?.querySelector(".o_login_popup_signup_submit_text");
        const spinner = button?.querySelector(".o_login_popup_spinner");
        const originalText = form.id.includes("professional")
            ? "Crear una cuenta profesional"
            : "Crear una cuenta particular";

        if (button) {
            button.disabled = loading;
        }
        if (text) {
            text.textContent = loading ? "Creando cuenta…" : originalText;
        }
        if (spinner) {
            spinner.hidden = !loading;
        }
    };

    const setResetLoading = (loading) => {
        if (!resetSubmitButton) {
            return;
        }
        resetSubmitButton.disabled = loading;
        if (resetSubmitText) {
            resetSubmitText.textContent = loading ? "Enviando…" : "Restablecer contraseña";
        }
        if (resetSpinner) {
            resetSpinner.hidden = !loading;
        }
    };

    const resetResetPasswordView = () => {
        setBoxError(resetErrorBox);
        if (resetForm) {
            resetForm.hidden = false;
            resetForm.querySelectorAll('input[name="recaptcha_token_response"]').forEach((input) => input.remove());
        }
        if (resetSuccess) {
            resetSuccess.hidden = true;
        }
        if (resetSuccessMessage) {
            resetSuccessMessage.textContent = "Te hemos enviado las instrucciones para restablecer tu contraseña.";
        }
        setResetLoading(false);
    };

    const showView = (name, focus = true) => {
        if (!views[name]) {
            return;
        }

        currentView = name;
        Object.entries(views).forEach(([viewName, element]) => {
            if (element) {
                element.hidden = viewName !== name;
            }
        });

        popup.classList.toggle("is-signup", ["signup-choice", "particular", "professional"].includes(name));
        popup.scrollTop = 0;

        if (!focus) {
            return;
        }

        window.setTimeout(() => {
            if (name === "login") {
                loginInput?.focus();
            } else if (name === "particular" || name === "professional") {
                views[name]?.querySelector(".o_login_popup_firstname")?.focus();
            } else if (name === "reset-password") {
                resetEmailInput?.focus();
            }
        }, 60);
    };

    const resetErrors = () => {
        setBoxError(loginErrorBox);
        popup.querySelectorAll(".o_login_popup_signup_error").forEach((box) => setBoxError(box));
        setBoxError(resetErrorBox);
    };

    const openPopup = (view = "login") => {
        if (closingTimer) {
            window.clearTimeout(closingTimer);
            closingTimer = null;
        }

        lastFocusedElement = document.activeElement;
        resetErrors();

        if (loginRedirectInput) {
            loginRedirectInput.value = currentRelativeUrl();
        }
        popup.querySelectorAll(".o_login_popup_signup_redirect").forEach((input) => {
            input.value = currentRelativeUrl();
        });
        if (resetRedirectInput) {
            resetRedirectInput.value = currentRelativeUrl();
        }
        if (view === "reset-password") {
            resetResetPasswordView();
        }

        showView(view, false);
        overlay.hidden = false;
        document.body.classList.add("o_login_popup_open");
        window.requestAnimationFrame(() => {
            overlay.classList.add("is-open");
            window.setTimeout(() => {
                if (view === "login") {
                    loginInput?.focus();
                } else if (view === "reset-password") {
                    resetEmailInput?.focus();
                }
            }, 80);
        });
    };

    const closePopup = () => {
        overlay.classList.remove("is-open");
        document.body.classList.remove("o_login_popup_open");
        closingTimer = window.setTimeout(() => {
            overlay.hidden = true;
            closingTimer = null;
            showView("login", false);
            if (lastFocusedElement instanceof HTMLElement) {
                lastFocusedElement.focus();
            }
        }, 180);
    };

    const getInternalPath = (anchor) => {
        if (!anchor || anchor.closest("#o_login_popup")) {
            return null;
        }
        try {
            const url = new URL(anchor.href, window.location.href);
            if (url.origin !== window.location.origin) {
                return null;
            }
            return url.pathname;
        } catch {
            return null;
        }
    };

    document.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }
        const anchor = event.target.closest?.("a[href]");
        const path = getInternalPath(anchor);
        if (path !== LOGIN_PATH && path !== SIGNUP_PATH && path !== RESET_PASSWORD_PATH) {
            return;
        }
        event.preventDefault();
        if (path === SIGNUP_PATH) {
            openPopup("signup-choice");
        } else if (path === RESET_PASSWORD_PATH) {
            openPopup("reset-password");
        } else {
            openPopup("login");
        }
    });

    popup.addEventListener("click", (event) => {
        const viewButton = event.target.closest?.("[data-login-popup-view]");
        if (viewButton) {
            event.preventDefault();
            const targetView = viewButton.dataset.loginPopupView;
            if (targetView === "reset-password") {
                resetResetPasswordView();
            }
            showView(targetView);
            return;
        }

        const signupCard = event.target.closest?.("[data-signup-type]");
        if (signupCard) {
            showView(signupCard.dataset.signupType);
            return;
        }

        if (event.target.closest?.("[data-signup-back]")) {
            showView("signup-choice");
        }
    });

    closeButton?.addEventListener("click", closePopup);

    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) {
            closePopup();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || overlay.hidden) {
            return;
        }
        if (currentView === "particular" || currentView === "professional") {
            showView("signup-choice");
        } else if (currentView === "reset-password") {
            showView("login");
        } else {
            closePopup();
        }
    });

    popup.querySelectorAll(".o_login_popup_password_toggle").forEach((toggle) => {
        toggle.addEventListener("click", () => {
            const field = toggle.closest(".o_login_popup_password_field");
            const input = field?.querySelector("input");
            if (!input) {
                return;
            }

            const isPassword = input.type === "password";
            input.type = isPassword ? "text" : "password";
            toggle.setAttribute("aria-pressed", isPassword ? "true" : "false");
            toggle.setAttribute("aria-label", isPassword ? "Ocultar contraseña" : "Mostrar contraseña");

            const icon = toggle.querySelector("i");
            if (icon) {
                icon.classList.toggle("fa-eye-slash", !isPassword);
                icon.classList.toggle("fa-eye", isPassword);
            }
            input.focus();
        });
    });

    const sessionIsAuthenticated = async () => {
        const response = await fetch("/web/session/get_session_info", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: {},
                id: Date.now(),
            }),
        });

        if (!response.ok) {
            return false;
        }

        const payload = await response.json();
        return Boolean(payload?.result?.uid);
    };

    const extractSignupError = async (response) => {
        try {
            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const alert = doc.querySelector(".alert-danger, .oe_login_form .alert, .oe_signup_form .alert");
            const message = alert?.textContent?.trim();
            if (message) {
                return message.replace(/\s+/g, " ");
            }
        } catch (error) {
            console.warn("[login_popup] No se pudo leer el error de registro:", error);
        }
        return "No se ha podido crear la cuenta. Revisa los datos e inténtalo de nuevo.";
    };

    const extractResetPasswordResult = async (response) => {
        try {
            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const success = doc.querySelector('.alert-success[role="status"], .oe_login_form .alert-success');
            const error = doc.querySelector('.alert-danger[role="alert"], .oe_reset_password_form .alert-danger');
            return {
                success: success?.textContent?.trim()?.replace(/\s+/g, " ") || "",
                error: error?.textContent?.trim()?.replace(/\s+/g, " ") || "",
            };
        } catch (error) {
            console.warn("[login_popup] No se pudo leer la respuesta de recuperación:", error);
            return { success: "", error: "" };
        }
    };

    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBoxError(loginErrorBox);

        if (!loginForm.reportValidity()) {
            return;
        }

        setLoginLoading(true);

        try {
            if (loginRedirectInput) {
                loginRedirectInput.value = currentRelativeUrl();
            }

            const response = await fetch(LOGIN_POPUP_AUTH_PATH, {
                method: "POST",
                body: new FormData(loginForm),
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });

            let result = null;
            try {
                result = await response.json();
            } catch (parseError) {
                console.warn("[login_popup] Respuesta de login no válida:", parseError);
            }

            if (!response.ok) {
                throw new Error(result?.message || `HTTP ${response.status}`);
            }

            if (result?.success) {
                window.location.reload();
                return;
            }

            setBoxError(
                loginErrorBox,
                result?.message || "Correo electrónico o contraseña incorrectos."
            );
            loginPasswordInput?.select();
        } catch (error) {
            console.error("[login_popup] Error al iniciar sesión:", error);
            setBoxError(loginErrorBox, "No se ha podido iniciar sesión. Inténtalo de nuevo.");
        } finally {
            setLoginLoading(false);
        }
    });

    resetForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBoxError(resetErrorBox);

        if (!resetForm.reportValidity()) {
            return;
        }

        if (resetRedirectInput) {
            resetRedirectInput.value = currentRelativeUrl();
        }
        setResetLoading(true);

        try {
            const response = await fetch(RESET_PASSWORD_PATH, {
                method: "POST",
                body: new FormData(resetForm),
                credentials: "same-origin",
                redirect: "follow",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await extractResetPasswordResult(response);
            if (result.success) {
                resetForm.hidden = true;
                if (resetSuccessMessage) {
                    resetSuccessMessage.textContent = result.success;
                }
                if (resetSuccess) {
                    resetSuccess.hidden = false;
                }
                return;
            }

            setBoxError(
                resetErrorBox,
                result.error || "No se ha podido enviar el correo de recuperación. Revisa el correo e inténtalo de nuevo."
            );
        } catch (error) {
            console.error("[login_popup] Error al restablecer contraseña:", error);
            setBoxError(resetErrorBox, "No se ha podido enviar el correo de recuperación. Inténtalo de nuevo.");
        } finally {
            setResetLoading(false);
        }
    });

    const syncProfessionalExtraFields = () => {
        if (!professionalExtraFields) {
            return;
        }

        const selectedType = professionalTypeInputs.find((input) => input.checked);
        const hasSelectedType = Boolean(selectedType);
        professionalExtraFields.hidden = !hasSelectedType;

        professionalExtraFields.querySelectorAll("input, select, textarea").forEach((field) => {
            field.disabled = !hasSelectedType;
        });

        if (professionalVatInput) {
            const vatLabel = selectedType?.value === "company" ? "CIF" : "NIF";
            professionalVatInput.placeholder = hasSelectedType ? vatLabel : "NIF / CIF";
            professionalVatInput.setAttribute("aria-label", `${vatLabel} obligatorio`);
            if (professionalVatLabel) {
                professionalVatLabel.textContent = `${vatLabel} (obligatorio)`;
            }
        }
    };

    professionalTypeInputs.forEach((input) => {
        input.addEventListener("change", syncProfessionalExtraFields);
    });
    syncProfessionalExtraFields();

    signupForms.forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const errorBox = form.querySelector(".o_login_popup_signup_error");
            setBoxError(errorBox);

            const password = form.querySelector('input[name="password"]');
            const confirmPassword = form.querySelector('input[name="confirm_password"]');
            if (password?.value !== confirmPassword?.value) {
                setBoxError(errorBox, "Las contraseñas no coinciden.");
                confirmPassword?.focus();
                return;
            }

            if (!form.reportValidity()) {
                return;
            }

            const firstName = form.querySelector(".o_login_popup_firstname")?.value.trim() || "";
            const lastName = form.querySelector(".o_login_popup_lastname")?.value.trim() || "";
            const fullName = form.querySelector(".o_login_popup_signup_fullname");
            const redirect = form.querySelector(".o_login_popup_signup_redirect");
            if (fullName) {
                fullName.value = `${firstName} ${lastName}`.trim();
            }
            if (redirect) {
                redirect.value = currentRelativeUrl();
            }

            setSignupLoading(form, true);

            try {
                const response = await fetch(SIGNUP_PATH, {
                    method: "POST",
                    body: new FormData(form),
                    credentials: "same-origin",
                    redirect: "follow",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                if (await sessionIsAuthenticated()) {
                    window.location.reload();
                    return;
                }

                const message = await extractSignupError(response);
                setBoxError(errorBox, message);
            } catch (error) {
                console.error("[login_popup] Error al registrar usuario:", error);
                setBoxError(errorBox, "No se ha podido crear la cuenta. Inténtalo de nuevo.");
            } finally {
                setSignupLoading(form, false);
            }
        });
    });
});
