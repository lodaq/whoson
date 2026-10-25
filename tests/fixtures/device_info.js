Atp.DeviceInfo = Em.Object.extend({
    Time: function() {
        return utilGetTimeString(this.UpTime, false);
    }.property("UpTime")
});
Atp.DeviceInfoController = Atp.SingleObjController.create ({
    modelClass: Atp.DeviceInfo,
    objName: 'system/deviceinfo',
    timerInterval: 1000,

    OUI_AND_SN: function() {
        if (typeof(this.content.ManufacturerOUI) != "undefined" || typeof(this.content.SerialNumber) != "undefined" ){
             return this.content.ManufacturerOUI + '-' + this.content.SerialNumber;
        }
        return "";
    }.property("content.ManufacturerOUI"),
    timerCallback: function() {
        var self = this;
        var counts = self.content.get('UpTime');
        self.content.set('UpTime', counts+1);
    }
});

Atp.DevInfoView = Atp.SingleObjView.extend ({
    bClosed: false,
    readOnly: true,
    hasHelpView: false,
    prefixName: 'deviceinfo',
    controller: Atp.DeviceInfoController,
    EditView: Em.View.extend ({
        template: Em.Handlebars.compile(' \
            {{ view Atp.LabelView textType="label" labelID="deviceinfo.product_type" valueBinding="content.DeviceName" }} \
            {{ view Atp.LabelView textType="label" labelID="deviceinfo.device_id" valueBinding="view.controller.OUI_AND_SN" }} \
            {{ view Atp.LabelView textType="label" labelID="deviceinfo.hardware" valueBinding="content.HardwareVersion" }} \
            {{ view Atp.LabelView textType="label" labelID="deviceinfo.software" valueBinding="content.SoftwareVersion" }} \
            {{ view Atp.LabelView textType="label" labelID="deviceinfo.uptime" valueBinding="content.Time" }} \
        ')
    })
});

Atp.WlanStatusItemView = Em.View.extend ({
    labelID: null,
    template: Em.Handlebars.compile(' \
        <label class="fontweight_thick">{{t labelID}}</label> \
        <div class="width_100p"> \
            {{ view Atp.LabelView textType="label" labelID="diagnose_wlan.ssid" valueBinding="view.content.SSID" }} \
            {{ view Atp.LabelView textType="label" labelID="diagnose_wlan.enable" valueBinding="view.content.EnableStr" }} \
            {{ view Atp.LabelView textType="label" labelID="Menu.MACAddress" valueBinding="view.content.BSSID" }} \
            {{ view Atp.LabelView textType="label" labelID="wlan.enc.mode" valueBinding="view.content.EncModeStr" }} \
            {{ view Atp.LabelView textType="label" labelID="wlan.ss.channel" valueBinding="view.content.ChannelStr" }} \
            {{ view Atp.LabelView textType="label" labelID="wlan.ss.transpwr" valueBinding="view.content.TransmitPowerStr" }} \
            {{ view Atp.LabelView textType="label" labelID="wlan.ss.cc" valueBinding="view.content.RegulatoryDomainStr"}}\
        </div> \
    ')
});

Atp.WlanStatusController = Atp.SingleObjController.create ({
    load: function(callback) {
        Atp.WlanBasicController.load(function() {
                if (callback){
                    callback();
                }
        });
    }
});

Atp.WlanStatusCollapse = Atp.SingleObjView.extend ({
    readOnly: true,
    hasHelpView: false,
    prefixName: 'wlan.info',
    controller: Atp.WlanStatusController,
    EditView: Em.View.extend ({
        template: Em.Handlebars.compile(' \
            {{view Atp.WlanStatusItemView labelID ="wlan.wifi.mi" contentBinding="Atp.WlanBasicController.content" }} \
        ')
    })
});


