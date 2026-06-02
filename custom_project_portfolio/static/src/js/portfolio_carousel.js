(function () {
    // Delegamos en el documento para capturar cualquier modal que se abra
    document.addEventListener('shown.bs.modal', function (e) {
        var modal = e.target;
        var initEl = modal.querySelector('.portfolio-carousel-init');
        if (!initEl) return;

        var carouselId = initEl.getAttribute('data-carousel-id');
        var total = parseInt(initEl.getAttribute('data-total'), 10);
        var carouselEl = document.getElementById(carouselId);
        var counterEl = document.getElementById('counter_' + carouselId.replace('carousel_', ''));

        if (!carouselEl || !counterEl || total <= 1) return;

        // Evitar registrar múltiples veces si el modal se abre varias veces
        if (carouselEl.dataset.counterBound) return;
        carouselEl.dataset.counterBound = '1';

        carouselEl.addEventListener('slide.bs.carousel', function (e) {
            counterEl.textContent = (e.to + 1) + ' / ' + total;
        });
    });
})();
