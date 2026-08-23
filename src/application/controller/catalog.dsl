{
  catalog_logic : {
    products:manager.storekeeper.gather(session, repository: "dummyjson");
    cart_count(default: 0) -> catalog_logic.cart_count;
    active_category(default: "all") -> catalog_logic.active_category;

    add_to_cart(deps: false) -> messenger.send(
      session: sid,
      domain: "catalog:catalog_logic.cart_count",
      payload: catalog_logic.cart_count + 1
    );

    show_all(deps: false) -> messenger.send(
      session: sid,
      domain: "catalog:catalog_logic.active_category",
      payload: "all"
    );

    show_beauty(deps: false) -> messenger.send(
      session: sid,
      domain: "catalog:catalog_logic.active_category",
      payload: "beauty"
    );

    show_fragrances(deps: false) -> messenger.send(
      session: sid,
      domain: "catalog:catalog_logic.active_category",
      payload: "fragrances"
    );
  }
}