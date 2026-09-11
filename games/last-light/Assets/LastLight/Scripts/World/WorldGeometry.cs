using System;
using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;

namespace LastLight
{
    // All visual assets are generated from these primitives; no opaque purchased packs.
    public static class WorldGeometry
    {
        static readonly Dictionary<string, Material> materials = new Dictionary<string, Material>();
        static TMP_FontAsset font;
        public static readonly Color Steel = Hex("405563"), Dark = Hex("172630"), Pale = Hex("D7D8CE"),
            Amber = Hex("E9B56F"), Green = Hex("75998C"), Warning = Hex("BC6556");

        public static Color Hex(string hex)
        {
            Color result;
            return ColorUtility.TryParseHtmlString("#" + hex, out result) ? result : Color.gray;
        }
        static Color BlueSteel()=>Hex("79A6B5");

        public static Material Mat(Color color, bool glow = false)
        {
            string key = ColorUtility.ToHtmlStringRGBA(color) + (glow ? "e" : "m");
            if (materials.TryGetValue(key, out var cached)) return cached;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var mat = new Material(shader) { name = "LL_" + key, color = color };
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            if (mat.HasProperty("_Smoothness")) mat.SetFloat("_Smoothness", 0.18f);
            if (glow)
            {
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", color * 0.7f);
            }
            materials[key] = mat;
            return mat;
        }

        public static GameObject Shape(Transform parent, string name, PrimitiveType type,
            Vector3 position, Vector3 scale, Color color, bool collider = false, bool glow = false)
        {
            GameObject go = GameObject.CreatePrimitive(type);
            go.name = name;
            go.transform.SetParent(parent, false);
            go.transform.localPosition = position;
            go.transform.localScale = scale;
            var mesh = go.GetComponent<Renderer>();
            mesh.sharedMaterial = Mat(color, glow);
            mesh.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
            if (!collider && go.TryGetComponent<Collider>(out var col)) UnityEngine.Object.Destroy(col);
            return go;
        }

        public static GameObject Box(Transform p, string n, Vector3 pos, Vector3 size, Color c,
            bool collider = false, bool glow = false) => Shape(p, n, PrimitiveType.Cube, pos, size, c, collider, glow);

        public static GameObject Group(Transform parent, string name, Vector3 position)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = position;
            return go;
        }

        public static TMP_FontAsset Font()
        {
            if (font != null) return font;
            var source = Resources.Load<Font>("Fonts/Chinese") ?? Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            font = TMP_FontAsset.CreateFontAsset(source, 36, 5, UnityEngine.TextCore.LowLevel.GlyphRenderMode.SDFAA,
                1024, 1024, TMPro.AtlasPopulationMode.Dynamic, true);
            font.name = "LastLight Chinese Dynamic";
            return font;
        }

        public static TextMeshPro Label(Transform parent, string text, Vector3 position, float size, Color color)
        {
            var go = Group(parent, "Label_" + text, position);
            var label = go.AddComponent<TextMeshPro>();
            label.font = Font();
            label.text = text;
            label.fontSize = size;
            label.color = color;
            label.alignment = TextAlignmentOptions.Center;
            label.rectTransform.sizeDelta = new Vector2(5f, 1.2f);
            label.richText = false;
            return label;
        }

        public static void Seat(Transform root,float x,float z,Color fabric,bool rear)
        {
            var group=Group(root,"SeatPair",new Vector3(x,0,z));
            foreach(float offset in new[]{-.31f,.31f})
            {
                var seat=UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop("seat"),group.transform,false);
                seat.transform.localPosition=new Vector3(offset,0,0);
                if(!rear)seat.transform.localRotation=Quaternion.Euler(0,180,0);
            }
        }

        public static void Carriage(Transform root, string room)
        {
            Box(root, "Floor", new Vector3(0, -.16f, 0), new Vector3(17, .3f, 5.2f), Hex("505C60"), true);
            Box(root, "Aisle", new Vector3(0, .003f, -.25f), new Vector3(15.8f, .014f, 1.1f), Hex("3F4E54"));
            Box(root, "RearWall", new Vector3(0, 1.55f, 2.6f), new Vector3(17, 3.1f, .16f), Hex("A3ADA7"));
            Box(root, "WindowBand", new Vector3(0, 1.72f, 2.47f), new Vector3(16.5f, 1.25f, .05f), Dark);
            Box(root, "LowerTrim", new Vector3(0, .65f, 2.39f), new Vector3(16.5f, .1f, .08f), Amber * .6f);
            for (int i = -3; i <= 3; i++)
            {
                float x = i * 2.1f;
                Box(root, "WindowFrame", new Vector3(x, 1.9f, 2.37f), new Vector3(1.85f, 1.15f, .1f), Steel);
                Box(root, "TunnelWindow", new Vector3(x, 1.9f, 2.3f), new Vector3(1.68f, .96f, .025f), Hex("101D29"));
                Box(root, "WindowReflection", new Vector3(x-.42f, 2.1f, 2.27f), new Vector3(.04f, .68f, .025f), Hex("567280"));
                Box(root, "LuggageShelf", new Vector3(x, 2.82f, 1.88f), new Vector3(1.9f, .09f, 1f), Steel);
                if (i % 2 == 0)
                    Box(root, "Suitcase", new Vector3(x+.2f, 3.02f, 1.9f), new Vector3(.6f,.33f,.4f), Hex("877660"));
                Color fabric = room == "cabin06" ? Hex("657C71") : room == "cabin05" ? Hex("5B727F") : Hex("756C67");
                Seat(root, x, 1.6f, fabric, true);
                if (i != 0 && i % 2 != 0) Seat(root, x, -1.95f, fabric * .83f, false);
            }
            for (int i = -2; i <= 2; i++)
            {
                Box(root, "EmergencyStrip", new Vector3(i*3f, 2.98f, 1.8f), new Vector3(1.5f,.055f,.18f), Amber, false, true);
                Box(root, "AuxSafetyLamp", new Vector3(i*3f, 2.95f, .85f), new Vector3(.9f,.06f,.18f), Steel);
            }
            Box(root, "CutawaySill", new Vector3(0, .08f, -2.65f), new Vector3(17,.16f,.13f), Steel);
            foreach (float side in new[] {-8.3f,8.3f})
            {
                Box(root,"EndFrame",new Vector3(side,1.5f,1.8f),new Vector3(.16f,3,.7f),Pale*.75f);
                Box(root,"DoorHeader",new Vector3(side,2.5f,0),new Vector3(.16f,.7f,3),Pale*.75f);
            }
            Label(root, room.Substring(room.Length-2) + "  /  客厢", new Vector3(6.4f,2.95f,2.27f), 2.3f, Dark);
        }

        public static void Service(Transform root)
        {
            Box(root,"Floor",new Vector3(0,-.16f,0),new Vector3(17,.3f,5.2f),Hex("48585E"),true);
            Box(root,"Wall",new Vector3(0,1.65f,2.6f),new Vector3(17,3.3f,.2f),Hex("687C83"));
            Box(root,"CableRace",new Vector3(0,2.8f,2.35f),new Vector3(16,.35f,.28f),Dark);
            for(int i=-7;i<8;i+=2)
            {
                Box(root,"WallRib",new Vector3(i,1.5f,2.38f),new Vector3(.12f,2.4f,.12f),Steel);
                Box(root,"FloorMark",new Vector3(i,.005f,-.85f),new Vector3(.6f,.02f,.08f),Amber*.8f);
            }
            Box(root,"Bench",new Vector3(1.1f,.7f,1.4f),new Vector3(4.5f,.13f,1.3f),Dark);
            Box(root,"BenchLegA",new Vector3(-.8f,.32f,1.6f),new Vector3(.1f,.7f,.1f),Steel);
            Box(root,"BenchLegB",new Vector3(2.9f,.32f,1.6f),new Vector3(.1f,.7f,.1f),Steel);
            Label(root,"AUX 06  /  检修间",new Vector3(0,3.02f,2.32f),2.6f,Pale);
            Box(root,"EmergencyLight",new Vector3(0,2.9f,1.9f),new Vector3(2.2f,.09f,.3f),Amber,false,true);
        }

        public static void Tunnel(Transform root)
        {
            Box(root,"WalkwayFloor",new Vector3(0,-.16f,0),new Vector3(17,.3f,5f),Hex("596463"),true);
            Box(root,"TunnelWall",new Vector3(0,1.6f,2.6f),new Vector3(17,3.5f,.35f),Hex("3F545D"));
            Box(root,"TrackBed",new Vector3(0,-.2f,-4.1f),new Vector3(17,.2f,2.3f),Dark);
            foreach(float z in new[]{-3.7f,-4.65f}) Box(root,"Rail",new Vector3(0,-.02f,z),new Vector3(17,.09f,.075f),Steel);
            for(int i=-8;i<=8;i++) Box(root,"Sleeper",new Vector3(i,-.09f,-4.15f),new Vector3(.2f,.08f,1.4f),Hex("625D54"));
            for(int i=-7;i<8;i+=3)
            {
                Box(root,"TunnelRib",new Vector3(i,1.5f,2.3f),new Vector3(.17f,3.2f,.3f),Steel);
                Box(root,"RouteLamp",new Vector3(i,1f,2.1f),new Vector3(.32f,.12f,.1f),Steel);
            }
            Box(root,"WalkwayLine",new Vector3(0,.008f,-2.2f),new Vector3(17,.018f,.07f),Amber);
            Label(root,"避险横通道  →",new Vector3(3,2.7f,2.23f),3,Green);
        }

        public static GameObject Prop(Transform root,string id,string state,Vector3 position)
        {
            string model=id.Contains("door")?"door":id=="cabinet"||id=="power_bus"?"cabinet":
                id=="cable_joint"?"joint":id=="radio"?"console":id=="fixed_phone"?"phone":id=="vent06"?"vent":
                id=="maintenance_log"||id=="manifest"?"clipboard":id=="oxygen"?"medical":id=="backup_supply"?"backup":"";
            var go=Group(root,"Object_"+id,position);
            if(model!="")UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop(model),go.transform,false);
            else if(id=="tool_rack"||id=="stretcher_rack")
                Box(go.transform,"EmptyShelf",new Vector3(0,.64f,0),new Vector3(1.8f,.12f,.6f),Steel);
            else if(id=="aisle07")
            {
                for(int i=0;i<2;i++)
                {var bag=UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop("tools"),go.transform,false);bag.name="LooseLuggage_"+i;bag.transform.localPosition=new Vector3(i*.6f,0,0);}
            }
            else if(id=="water_point")
                Box(go.transform,"WaterDispenser",new Vector3(0,.85f,0),new Vector3(.7f,1.7f,.6f),Pale);
            else if(id=="passenger_bag"||id=="luggage06")
                UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop("tools"),go.transform,false);
            else if(id=="refuge")
            {
                UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop("door"),go.transform,false);
                Box(go.transform,"RefugeExit",new Vector3(0,2.3f,0),new Vector3(1.4f,.18f,.12f),Green,false,true);
            }
            else if(id=="walkway"||id=="signal_marker")
                Box(go.transform,"PathMarker",new Vector3(0,.015f,0),new Vector3(1,.035f,.18f),Steel);
            PresentationSockets.Attach(go,id);if(id.Contains("door"))PresentationSockets.Attach(go,"door");
            ApplyPropState(go,id,state);return go;
        }
        public static void ApplyPropState(GameObject go,string id,string state)
        {
            if(id.Contains("door"))
            {
                var block=go.transform.Find("PassageBlocker");
                if(block==null)
                {var node=Group(go.transform,"PassageBlocker",new Vector3(0,1,0));var collider=node.AddComponent<BoxCollider>();collider.size=new Vector3(1.18f,2,.16f);block=node.transform;}
                block.gameObject.SetActive(state!="open");
                foreach(var t in go.GetComponentsInChildren<Transform>())if(t.name=="DoorLeaf")t.localPosition=new Vector3(state=="open"?1.03f:0,0,0);
                if(id=="blocked_door")
                {
                    var cart=go.transform.Find("DisplacedTrolley");
                    if(cart==null)
                    {cart=UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop("cart"),go.transform,false).transform;cart.name="DisplacedTrolley";}
                    cart.localPosition=state=="jammed"?new Vector3(.28f,0,-.25f):new Vector3(1.35f,0,.4f);
                    cart.localRotation=Quaternion.Euler(0,state=="jammed"?14:75,state=="jammed"?-12:0);
                }
            }
            if(id=="cabinet"||id=="power_bus"||id=="cable_joint"||id=="radio"||id=="fixed_phone"||id=="vent06")
            {
                var indicator=go.transform.Find("StateIndicator");
                if(indicator==null)indicator=Box(go.transform,"StateIndicator",new Vector3(.16f,1.15f,-.22f),new Vector3(.09f,.05f,.018f),Steel).transform;
                bool ready=state=="tested"||state=="powered"||state=="ready";
                bool live=state=="live";Color color=ready?Green:live?Warning:state=="repaired"?Amber:state.Contains("isolated")?BlueSteel():Steel;
                indicator.GetComponent<Renderer>().sharedMaterial=Mat(color,ready||live);
                var status=go.transform.Find("DeviceStatus");
                var label=status!=null?status.GetComponent<TextMeshPro>():Label(go.transform,"",new Vector3(0,1.7f,0),1.1f,Pale);
                label.gameObject.name="DeviceStatus";
                label.text=state=="repaired"?"待复测":state=="tested"?"复测通过":state.Contains("isolated")?"已隔离":ready?"可用":state=="live"?"仍有供电":"";
            }
            if(id=="aisle07")
                foreach(var child in go.GetComponentsInChildren<Transform>().Where(t=>t.name.StartsWith("LooseLuggage_")))
                    child.localPosition=new Vector3(child.name.EndsWith("0")?-.45f:.45f,0,state=="clear"?1.0f:0);
            if(id=="cable_joint")
            {
                var damage=go.transform.Find("ObservedJoint");
                if(damage==null)damage=Box(go.transform,"ObservedJoint",new Vector3(0,.42f,-.2f),new Vector3(.22f,.15f,.025f),Dark).transform;
                bool observed=state=="diagnosed"||state=="isolated_diagnosed";bool repaired=state=="repaired"||state=="tested"||state=="powered";
                damage.gameObject.SetActive(observed||repaired);damage.GetComponent<Renderer>().sharedMaterial=Mat(observed?Hex("32251F"):Green);
            }
            if(id=="walkway")foreach(var r in go.GetComponentsInChildren<Renderer>())r.sharedMaterial=Mat(state=="lit"?Green:Steel,state=="lit");
        }

        public static void Cable(Transform p,Vector3 from,Vector3 to,Color color)
        {
            Vector3 delta=to-from;
            var go=Shape(p,"Cable",PrimitiveType.Cylinder,(from+to)*.5f,new Vector3(.025f,delta.magnitude*.5f,.025f),color);
            go.transform.localRotation=Quaternion.FromToRotation(Vector3.up,delta.normalized);
        }
    }
}
