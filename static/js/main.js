document.addEventListener('DOMContentLoaded', () => {
    // 1. Toast შეტყობინების ჩვენება გვერდის გადატვირთვის გარეშე
    function showToast(message) {
        let container = document.getElementById('toastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toastContainer';
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            container.style.zIndex = '1080';
            document.body.appendChild(container);
        }

        const toastEl = document.createElement('div');
        toastEl.className = 'toast align-items-center text-bg-dark border-0 shadow-lg rounded-3';
        toastEl.setAttribute('role', 'alert');
        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body d-flex align-items-center gap-2">
                    <i class="bi bi-check-circle-fill text-success"></i>
                    <span>${message}</span>
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        container.appendChild(toastEl);
        const bsToast = new bootstrap.Toast(toastEl, { delay: 2600 });
        bsToast.show();
        toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
    }

    // 2. AJAX კალათაში დამატება (გვერდის გადატვირთვის გარეშე)
    document.querySelectorAll('form[action*="/cart/add/"]').forEach(form => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalHtml = submitBtn.innerHTML;
            submitBtn.disabled = true;

            try {
                const formData = new FormData(form);
                const res = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                const data = await res.json();
                if (data.success) {
                    const badge = document.getElementById('navCartBadge');
                    if (badge) {
                        badge.textContent = data.cart_count;
                        badge.style.display = 'inline-block';
                    }
                    showToast(data.message);
                }
            } catch (err) {
                form.submit();
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalHtml;
            }
        });
    });

    // 3. AJAX Wishlist / Like ღილაკი
    document.querySelectorAll('.btn-wishlist[data-product-id]').forEach(btn => {
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
                    btn.innerHTML = data.liked
                        ? '<i class="bi bi-heart-fill"></i>'
                        : '<i class="bi bi-heart"></i>';
                }
            } catch (err) {
                console.error(err);
            }
        });
    });

    // 4. გადახდის მეთოდის გადართვა Checkout გვერდზე
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