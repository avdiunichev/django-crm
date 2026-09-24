(() => {
    const notify = () => {
        if (window.CRMToasts?.show) window.CRMToasts.show("Заполните обязательное поле", "error", 5000);
        else window.UIkit?.notification({message: "Заполните обязательное поле", status: "danger", timeout: 5000});
    };
    const enhanceWithin = (scope = document) => {
        scope.querySelectorAll('[data-driver-form]').forEach(form => {
            if (form.dataset.validationReady) return;
            form.dataset.validationReady = 'true';
            form.querySelectorAll('.field').forEach(wrapper => {
                if (!wrapper.querySelector('.field-error, .errorlist')) return;
                wrapper.querySelectorAll('input, select, textarea').forEach(field => field.setAttribute('aria-invalid', 'true'));
            });
            form.addEventListener('submit', event => {
                const invalid = [...form.querySelectorAll('input, select, textarea')].filter(field =>
                    field.willValidate && !field.closest('[hidden]') && !field.validity.valid);
                invalid.forEach(field => field.setAttribute('aria-invalid', 'true'));
                if (invalid.length) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    notify();
                    invalid[0].focus();
                }
            }, true);
            form.addEventListener('input', event => {
                if (event.target.validity?.valid) event.target.removeAttribute('aria-invalid');
            });
        });
    };
    document.addEventListener('DOMContentLoaded', () => {
        enhanceWithin();
        if (document.querySelector('[data-driver-form] .field-error, [data-driver-form] .errorlist')) notify();
    });
    window.CRMDriverValidation = {enhanceWithin};
})();
