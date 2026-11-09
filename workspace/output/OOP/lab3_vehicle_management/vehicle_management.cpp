// Lab Assignment 3: Vehicle Management System
// Single inheritance (Car, Truck, Motorcycle) and multiple inheritance
// (ElectricVehicle derives from Vehicle and Battery).

#include <iostream>
#include <string>
#include <vector>
using namespace std;

// ---------- Base class ----------
class Vehicle {
protected:
    string vehicleNumber;
    string brand;
    string model;
    double enginePower; // kW

public:
    Vehicle(const string& vn, const string& b, const string& m, double ep)
        : vehicleNumber(vn), brand(b), model(m), enginePower(ep) {}

    virtual ~Vehicle() {}

    void displayVehicle() const {
        cout << "Vehicle Number : " << vehicleNumber << "\n"
             << "Brand          : " << brand << "\n"
             << "Model          : " << model << "\n"
             << "Engine Power   : " << enginePower << " kW\n";
    }

    virtual void display() const {
        cout << "--- Vehicle ---\n";
        displayVehicle();
    }
};

// ---------- Single inheritance ----------
class Car : public Vehicle {
    int seats;

public:
    Car(const string& vn, const string& b, const string& m, double ep, int s)
        : Vehicle(vn, b, m, ep), seats(s) {}

    void display() const override {
        cout << "--- Car ---\n";
        displayVehicle();
        cout << "Seats          : " << seats << "\n";
    }
};

class Truck : public Vehicle {
    double payloadTons;

public:
    Truck(const string& vn, const string& b, const string& m, double ep, double payload)
        : Vehicle(vn, b, m, ep), payloadTons(payload) {}

    void display() const override {
        cout << "--- Truck ---\n";
        displayVehicle();
        cout << "Payload        : " << payloadTons << " tons\n";
    }
};

class Motorcycle : public Vehicle {
    int engineCC;

public:
    Motorcycle(const string& vn, const string& b, const string& m, double ep, int cc)
        : Vehicle(vn, b, m, ep), engineCC(cc) {}

    void display() const override {
        cout << "--- Motorcycle ---\n";
        displayVehicle();
        cout << "Engine Capacity: " << engineCC << " cc\n";
    }
};

// ---------- Separate Battery class ----------
class Battery {
protected:
    double capacityKWh;
    double voltage;
    string batteryType;

public:
    Battery(double cap, double volt, const string& type)
        : capacityKWh(cap), voltage(volt), batteryType(type) {}

    void displayBattery() const {
        cout << "Battery Type   : " << batteryType << "\n"
             << "Capacity       : " << capacityKWh << " kWh\n"
             << "Voltage        : " << voltage << " V\n";
    }
};

// ---------- Multiple inheritance ----------
class ElectricVehicle : public Vehicle, public Battery {
    int rangeKm;

public:
    ElectricVehicle(const string& vn, const string& b, const string& m, double ep,
                    double cap, double volt, const string& type, int range)
        : Vehicle(vn, b, m, ep), Battery(cap, volt, type), rangeKm(range) {}

    void display() const override {
        cout << "--- Electric Vehicle ---\n";
        displayVehicle();
        displayBattery();
        cout << "Range          : " << rangeKm << " km\n";
    }
};

// ---------- Test ----------
int main() {
    Car car("MH12AB1234", "Maruti", "Swift", 62.0, 5);
    Truck truck("MH14CD5678", "Tata", "Ace", 22.0, 0.75);
    Motorcycle bike("MH12EF9012", "Honda", "Shine", 7.7, 125);
    ElectricVehicle ev("MH12GH3456", "Tata", "Nexon EV", 95.0, 30.2, 350.0, "Lithium-ion", 312);

    // Single object calls
    car.display();
    cout << endl;
    truck.display();
    cout << endl;
    bike.display();
    cout << endl;
    ev.display();
    cout << endl;

    // Polymorphism through base class pointers
    vector<Vehicle*> fleet = {&car, &truck, &bike, &ev};
    cout << "=== Fleet (via base class pointers) ===\n";
    for (const Vehicle* v : fleet) {
        v->display();
        cout << endl;
    }

    return 0;
}
