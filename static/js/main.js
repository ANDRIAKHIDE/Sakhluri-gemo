document.addEventListener('DOMContentLoaded', () => {
    // AJAX Like ღილაკი
    document.querySelectorAll('.btn-like[data-product-id]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            const productId = btn.dataset.productId;
            try {
                const res = await fetch(`/product/${productId}/like`, {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (res.redirected) {
                    window.location.href = res.url;
                    return;
                }
                const data = await res.json();
                if (data.success) {
                    btn.classList.toggle('liked', data.liked);
                    btn.innerHTML = data.liked ? '❤️' : '🤍';
                }
            } catch (err) {
                console.error(err);
            }
        });
    });

    // გადახდის მეთოდის არჩევა Checkout გვერდზე
    const paymentRadios = document.querySelectorAll('input[name="payment_method"]');
    const receiptSection = document.getElementById('receiptUploadSection');
    if (paymentRadios.length && receiptSection) {
        paymentRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                receiptSection.style.display = (radio.value === 'transfer') ? 'block' : 'none';
            });
        });
    }
});
