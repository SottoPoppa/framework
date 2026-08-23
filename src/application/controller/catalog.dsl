{
  catalog_logic : {
    products(default: [
      {
        "name": "Taccuino modulare";
        "slug": "taccuino-modulare";
        "description": "Copertina rigida e pagine sostituibili per organizzare le idee.";
        "price": 18.5;
        "category": "cartoleria";
        "sku": "NM-001"
      },
      {
        "name": "Lampada da scrivania";
        "slug": "lampada-da-scrivania";
        "description": "Luce regolabile e struttura compatta per il lavoro quotidiano.";
        "price": 42;
        "category": "casa";
        "sku": "NM-002"
      },
      {
        "name": "Borraccia termica";
        "slug": "borraccia-termica";
        "description": "Acciaio riutilizzabile, mantiene la temperatura per tutta la giornata.";
        "price": 24;
        "category": "quotidiano";
        "sku": "NM-003"
      },
      {
        "name": "Organizer da tavolo";
        "slug": "organizer-da-tavolo";
        "description": "Vani essenziali per tenere in ordine strumenti e piccoli oggetti.";
        "price": 15;
        "category": "cartoleria";
        "sku": "NM-004"
      },
      {
        "name": "Cuffie pieghevoli";
        "slug": "cuffie-pieghevoli";
        "description": "Audio nitido e design leggero per concentrarsi senza ingombro.";
        "price": 49;
        "category": "tecnologia";
        "sku": "NM-005"
      },
      {
        "name": "Set di spezie";
        "slug": "set-di-spezie";
        "description": "Sei aromi essenziali in contenitori ordinati e riutilizzabili.";
        "price": 21;
        "category": "cucina";
        "sku": "NM-006"
      }
    ]) -> catalog_logic.products;
    cart_count(default: 0) -> catalog_logic.cart_count;

    add_to_cart(deps: false) -> messenger.send(
      session: sid,
      domain: "catalog:catalog_logic.cart_count",
      payload: catalog_logic.cart_count + 1
    );
  }
}