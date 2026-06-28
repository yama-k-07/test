# table = {"dev1": {
#             "username": "Tanaka",
#             "report": False,
#             "mac01" : "02",
#             "mac02" : "03"
#         },
#         "dev2": {
#             "username": "To-ki-ta",
#             "report": True,
#             "mac01" : "01",
#             "mac02" : "02"
#         }
#         }


dev_info =[{"dev_id": 1,
            "username": "Tanaka",
            "report": False,
            "mac01" : "02",
            "mac02" : "03"
            },
            {"dev_id": 2,
            "username": "To-ki-ta",
            "report": True,
            "mac01" : "01",
            "mac02" : "02"
            }]



def Location_estimation(table):
    try:
        # response = supabase.table(TABLE_AREA).select("*").execute()
        response = [{'bssid': '01', 'area': 1}, {'bssid': '02', 'area': 2}, {'bssid': '03', 'area': 3}]
        area_dict = {}
        for item in response:
            # item は既に辞書なので、response[item] ではなく item を使う
            area_dict[item["bssid"]] = item["area"]

        output = list()
        for item in table:
            # item は既に辞書なので、table[item] ではなく item を使う
            # output.append({"dev_id": item["dev_id"], "area": area_dict[item["mac01"]]})
            output.append({"area_id": area_dict[item["mac01"]],"username": item["username"], "device_id": item["dev_id"]})
        
        return output

    except Exception as e:
        # return jsonify({"error": str(e)}), 500
        return e 
    

data = Location_estimation(dev_info)
print(data)