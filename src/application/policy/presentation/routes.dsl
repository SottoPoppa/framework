routes: {
    route:GET_INDEX := { path:"/"; method:"GET"; "type":"view"; view:"terminal.xml"; controllers:["terminal", "chat"] };
    route:GET_CHAT := { path:"/chat"; method:"GET"; "type":"view"; view:"chat.xml"; controllers:["chat"] };
    route:GET_ECOMMERCE := { path:"/shop"; method:"GET"; "type":"view"; view:"ecommerce.xml"; controllers:["catalog"] };
    route:GET_PROFILE := { path:"/profile"; method:"GET"; "type":"view"; view:"profile.xml" };
    // Auth
    route:GET_LOGIN := { path:"/login"; method:"GET"; "type":"view"; view:"login.xml" };
    route:GET_LOGOUT := { path:"/logout"; method:"GET"; "type":"view"; view:"auth/logout.xml" };
    route:POST_LOGIN := { path:"/login"; method:"POST"; "type":"authenticate"; view:"auth/login.xml" };
    route:POST_LOGOUT := { path:"/logout"; method:"POST"; "type":"terminate"; view:"auth/logout.xml" };
    route:GET_SIGNUP := { path:"/signup"; method:"GET"; "type":"view"; view:"auth/signup.xml" };
    route:POST_SIGNUP := { path:"/signup"; method:"POST"; "type":"activate"; };
    route:GET_RECOVERY := { path:"/recovery"; method:"GET"; "type":"reinstate"; view:"auth/signup.xml" };
    route:POST_RECOVERY := { path:"/recovery"; method:"POST"; "type":"reinstate"; };
    // Admin
    route:GET_ADMIN := { path:"/admin"; method:"GET"; "type":"view"; view:"admin.xml" };
    // Error
    route:GET_ERROR_404 := { path:"/404"; method:"GET"; "type":"view"; view:"error/404.xml" };
    // Twitch
    route:GET_BROWSER := { path:"/browse"; method:"GET"; "type":"view"; view:"twitch_browse.xml" };
    route:GET_HOME := { path:"/home"; method:"GET"; "type":"view"; view:"twitch_home.xml" };
    route:GET_USER_PROFILE := { path:"/user/{id}"; method:"GET"; "type":"view"; view:"twitch_channel.xml" };
    route:GET_TRIS := { path:"/tris"; method:"GET"; "type":"view"; view:"tris.xml"; controllers:["tris"] };
    // SCRUM Kanban Board
    route:GET_KANBAN := { path:"/"; method:"GET"; "type":"view"; view:"kanban.xml"; controllers:["kanban"] };
}