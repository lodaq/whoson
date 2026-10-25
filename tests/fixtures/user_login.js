
/*******************************
  Controller
 *******************************/
 //level 1:user;2:admin,4:support

// LogCfg Controller
Atp.LoginController = Atp.SingleObjController.create ({
  objName     : 'system/user_login',
  count       : 0,
  errCsrfProc: function(result) {
      utilUpdateCsrf(result.csrf_param, result.csrf_token);
      this.postData();
  },

  postData: function() {
      this.content.set("UserName", $("#index_username").val());
      this.content.set("Password", $("#password").val());
      var csrf_obj = utilGetCsrf(); 
      var post_data = {
        "csrf": csrf_obj,
        "data": utilGetJson(this.content)
      };
      $('#password').blur();
      var plaintPwd = this.content.get("UserName") + base64Encode(SHA256(this.content.get("Password"))) + csrf_obj.csrf_param +csrf_obj.csrf_token;
      post_data["data"]["Password"] = SHA256(plaintPwd);
      this.post($.toJSON(post_data), function (result) {
        if ("ok" == result['errorCategory']) {
          g_userLevel = result['level'] ;
          if (typeof LoginCallBack === "function") {
            LoginCallBack(result);
          }else if ((result['IsFirst'] == false) && ( (result['level'] == 2) || (result['level'] == 1) || (Atp.IndexLanDeviceCountController.content.get("UserNumber") == 1)) ) {
            utilLoadJavascript("/js/firstlogin.js");
            g_userLevel = result['level'];
          } else { 
            window.location.href ="/html/wizard/wizard.html";
          }
        } else if (1 != result.errcode) {
          Atp.LoginController.set('count', result['count']);
          if ((1 == result['errcode']) && ("" != result['csrf'])) {
            $("#errorCategory").html(Em.I18n.t(result['csrf']));
          } else {
            $("#errorCategory").html(Em.I18n.t("UserLogin." + result['errorCategory'], {arg1: 3-Atp.LoginController.count, count: Atp.LoginController.count}));
          }
        }
      });
    }
});

Atp.AdminNameController = Atp.MultiObjController.create ({
  objName: 'system/useraccount'
});

Atp.UserFindUserNamePasswordView = Em.View.extend({
  classNames:'accordion-group',
  tagName:'div',
  elementId:"user_find",
  template: Em.Handlebars.compile('\
    <div class="accordion-heading marginright_35"> \
      <div id="collapseinfo_1" class="text_right paddingright_15 index_page_font_color accordion-toggle text_underline">{{t UserLogin.Resolve}}</div> \
    </div> \
    <div id="collapse_1" class="hide"> \
      <div class="accordion-inner"> \
        <div class="rounddiv getaccount_part"> \
          <div class="bodydiv rounddiv paddingtop_8 getaccount_part_body index_page_font_color" align="center"> \
              &nbsp;&nbsp;&nbsp;{{t UserLogin.username_password }}</div> \
          <div class="bodydiv rounddiv getaccount_info paddingbottom_20" align="center"> \
              <div class="index_page_font_color text_left">{{t UserLogin.defaultup_guide }}</div>  \
          </div> \
        </div> \
      </div> \
    </div>')
})

Atp.UserAccountRestoreView = Em.View.extend({
  classNames:'accordion-group margintop_15',
  tagName:'div',
  elementId:"user_restore",
  template: Em.Handlebars.compile('\
    <div class="accordion-heading marginright_35"> \
      <div id="collapseinfo_2" class="text_right paddingright_15 index_page_font_color accordion-toggle text_underline">{{t UserLogin.forgetps }}</div> \
    </div> \
    <div id="collapse_2" class="hide"> \
      <div class="accordion-inner"> \
        <div class="rounddiv getaccount_part"> \
          <div class="bodydiv rounddiv paddingtop_8 getaccount_part_body index_page_font_color"> \
            &nbsp;&nbsp;&nbsp;{{t UserLogin.restore_username_password }} \
          </div> \
          <div class="getaccount_info"> \
            <div class="bodydiv rounddiv" align="center"> \
          <div class="text_left index_page_font_color">{{t UserLogin.restoredefaultop_guide}}</div> \
          <div class="text_left"><font color="#FF0000">{{t UserLogin.restore_attention}}</font></div> \
          </div> \
	        </div> \
        </div> \
      </div> \
    </div>')
})


function create_login_block(index) {
  var login_str = '';
  if (index) {
    login_str = '<div class="width_100p index_page_us_ps_top_div height_3" id="index_login_content">&nbsp;</div>'
  } else {
    login_str = '<div id="output_login_internal" class="header height_20" style="background-color:#23384B;" align="right">\
        <button id="index_window" type="button" class="close_detail marginright_5">X</button></div>';
  }
  login_str +='<div class="margintop_20 text_left paddingleft_5p login_font_color fontsize_18">' + Em.I18n.t("index.Login") + '</div> \
              <div class="margintop_15" align="center"> \
                <table id="input_username_pass" class="login_table width_400" cellspacing="0"> \
                <tr class="height_25"> \
                  <td class="login_first_row_first_td login_first_row_first_td_r width_35"> \
                    <label class="pull-left margintop_5 ie6marginleft_10 ic-name ie6image"></label> \
                  </td> \
                  <td class="login_first_row_second_td paddingleft_5 paddingright_5 width_70 text_left">' + Em.I18n.t("UserLogin.UserName") + '</td> \
                  <td class="login_first_row_third_td"> \
                    <input id="index_username" type="text" style="border:none;margin-bottom:0px;height:100%;width:98%;" maxlength=32/> \
                  </td> \
                </tr> \
                <tr class="height_25"> \
                  <td class="login_second_row_first_td login_first_row_first_td_r width_35"> \
                    <label class="pull-left ie6password ic-password ie6image"></label> \
                  </td> \
                  <td class="login_second_row_second_td paddingleft_5 paddingright_5 width_70 text_left">' + Em.I18n.t("UserLogin.Password") + '</td> \
                  <td class="login_second_row_third_td"> \
                    <input id="password" type="password" autocomplete="off" style="border:none;margin-bottom:0px;height:100%;width:98%;" maxlength=32/> \
                  </td> \
                </tr> \
                </table><br> \
              </div> \
              <div class="loginerrorinfo" align="center"><div class="errorInfo"><font id="errorCategory" color="#FF0000"></font><br></div></div>';
              if (index) {} else {
                  login_str += '<div class="login_cancel_div paddingtop_10 paddingbottom_10 text_center"> \
                    <button id="loginbtn" onclick="Atp.LoginController.postData();">' + Em.I18n.t("UserLogin.LoginLabel") + '</button> \
                  </div>';
              }
              login_str += '<div class="margintop_15 min_height_52"><div class="accordion" id="accordion_help"></div>';
              if (index) {
                login_str += '<div class="login_cancel_div paddingtop_10 paddingbottom_10 text_center"> \
                  <button id="loginbtn" onclick="Atp.LoginController.postData();" class="loginfontcolor">' + Em.I18n.t("UserLogin.LoginLabel") + '</button> \
                </div>';
              }
              login_str += '</div>';
  return login_str;
}
var loginviewnum = 2;
var infoshow_1 = false;
var infoshow_2 = false;
var infoshow_3 = false;
function init_login_block() {
  // Set default key proc
  $("body").keydown(function(e) {
      var curKey = e.which;
      if(curKey == 13) {
          $("#loginbtn").click();
          return false;
      }
  });
  // Show default user name and set focus
  Atp.AdminNameController.load(function() {
    var admincontent = Atp.AdminNameController.content;
    var gotUsername = false;
    if (admincontent)
    {
      if (admincontent.length == 1) {
        if (admincontent[0]["username"])
        {
          Atp.LoginController.content.set("UserName", admincontent[0]["username"]);
          gotUsername = true;
        }
      } else {
        for(var i=0;i<admincontent.length;i++){
	  if ((admincontent[i]["userlevel"] == 2) && (admincontent[i]["username"]))
          {
            Atp.LoginController.content.set("UserName",admincontent[i]["username"]);
            gotUsername = true;
            break;
          } 
        } 
      }
    }
    if (gotUsername) {
      $("#password").focus();
      if(typeof $.cookie("username") != "undefined" && $.cookie("username") != "" && $.cookie("username") != null){
        $("#index_username").val($.cookie("username"));
      }else{
        $("#index_username").val(Atp.LoginController.content.get("UserName"));
      } 
    } else {
      $("#index_username").focus();
    }
  });

  function clickeachfunc(viewid, totalnum, infoshow){
      var i=1;
      var showstatus = false;
      if ((viewid <= 0) || (viewid > totalnum))
      {
          return showstatus;
      }
      for (i=1; i<=totalnum; i++)
      {
          if (i != viewid)
          {
              $('#collapse_'+i).hide(100);
          }
      }
      if(infoshow)
      {
          $('#collapse_'+viewid).hide(100);         
      }
      else
      {
          $('#collapse_'+viewid).show(100);
          showstatus = true;
      }
      return showstatus;
  }
  // Do animation
  $("#collapseinfo_1").live("click",function(){

      infoshow_2 = false;
      infoshow_3 = false;
      infoshow_1 = clickeachfunc(1, loginviewnum, infoshow_1);
  });
  $("#collapseinfo_2").live("click",function(){
      infoshow_1 = false;
      infoshow_3 = false;
      infoshow_2 = clickeachfunc(2, loginviewnum, infoshow_2);
  });

}

if ($("#login_window").length > 0) {
  var loginBlock = create_login_block(true);
  $("#login_window").html(loginBlock);
  init_login_block();
  Atp.UserAccountRestoreView.create().appendTo('#accordion_help');
} else if ($("#output_login").length > 0) {
  var loginBlock = create_login_block();
  $("#output_login").html(loginBlock);
  init_login_block();
  ApplicationdynamicShow("output_login","backgroundPopup");
  Atp.UserAccountRestoreView.create().appendTo('#accordion_help');
}
