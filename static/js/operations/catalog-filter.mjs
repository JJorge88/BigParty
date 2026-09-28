export function normalize(value) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es').trim();
}

export function filterProducts(products, category, search) {
  const query = normalize(search);
  return products.filter(product => (!category || String(product.category_id) === String(category)) && normalize(product.name).includes(query));
}
