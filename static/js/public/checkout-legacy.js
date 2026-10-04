(function () {
  var checkout = document.querySelector('[data-checkout]');
  if (!checkout || checkout.getAttribute('data-enhanced') === 'true') return;
  var quantities = checkout.querySelectorAll('[data-price]');
  var total = checkout.querySelector('[data-total-display]');
  var action = checkout.querySelector('[data-purchase-action]');
  var guest = checkout.querySelector('[data-checkout-guest]');

  function clamp(input, delta) {
    var value = parseInt(input.value, 10) || 0;
    var maximum = parseInt(input.max, 10) || 0;
    input.value = Math.max(0, Math.min(maximum, value + delta));
  }
  function update() {
    var cents = 0;
    for (var i = 0; i < quantities.length; i += 1) {
      cents += (parseInt(quantities[i].value, 10) || 0) * Math.round(parseFloat(quantities[i].getAttribute('data-price')) * 100);
      var stepper = quantities[i].parentNode;
      stepper.querySelector('[data-delta="-1"]').disabled = Number(quantities[i].value) <= 0;
      stepper.querySelector('[data-delta="1"]').disabled = Number(quantities[i].value) >= Number(quantities[i].max);
    }
    total.textContent = 'Q' + (cents / 100).toLocaleString('en-US', {minimumFractionDigits: cents % 100 ? 2 : 0, maximumFractionDigits: 2});
    action.disabled = cents <= 0 || checkout.hasAttribute('data-preview');
  }
  var buttons = checkout.querySelectorAll('[data-delta]');
  for (var i = 0; i < buttons.length; i += 1) {
    buttons[i].addEventListener('click', function () {
      var input = this.parentNode.querySelector('input');
      clamp(input, parseInt(this.getAttribute('data-delta'), 10));
      update();
    });
  }
  for (var j = 0; j < quantities.length; j += 1) quantities[j].addEventListener('input', update);
  guest.hidden = true;
  action.type = 'button';
  action.textContent = 'Continuar ↗';
  action.addEventListener('click', function () {
    if (guest.hidden) {
      guest.hidden = false;
      guest.scrollIntoView();
      var field = guest.querySelector('input');
      if (field) field.focus();
      action.textContent = 'Confirmar y pagar ↗';
    } else checkout.submit();
  });
  checkout.setAttribute('data-enhanced', 'true');
  update();
}());
