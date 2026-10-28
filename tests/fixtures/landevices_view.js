Atp.LoadHelper.appendLangRes("host_info_res.js");
Atp.LoadHelper.appendJs("/js/host_info.js");
Atp.LoadHelper.appendJs("/js/landevices.js");
Atp.LoadHelper.loadAll();

Atp.LanDevicesContainerView = Atp.PageContainerView.extend({
    prefixName: "landev",
    repageload:function(){
        if(Atp.HostsController.get("objName") != "system/HostInfo"){
            Atp.HostsController.set("objName","system/HostInfo");
            Atp.AllHostsController.load(function(){
                Atp.HostsController.load();
            });
        }
    },
    dataView: Em.View.extend ({
        template: Em.Handlebars.compile('{{view Atp.LanDeviceCollapseView}}')
    })
});

Atp.MenuController.createSubmenuView(Atp.LanDevicesContainerView, "landevices");