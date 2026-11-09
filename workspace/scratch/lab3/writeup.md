**Progressive Education Society's MODERN COLLEGE OF ENGINEERING**
Shivajinagar, Pune - 411005
(An Autonomous Institute Affiliated to Savitribai Phule Pune University)
Level 4.5 First Year B.Tech. (2026 Pattern)

---

**Assignment No.:** 3

**Title:** Vehicle Management System

**Course Outcome:**

**Date of Completion:** 06/11/2026

**Assessment Grade / Marks:**

**Assessor's Sign with Date:**

---

**Progressive Education Society's MODERN COLLEGE OF ENGINEERING**
Shivajinagar, Pune - 411005

**Roll No.:** 19
**Name:** Shardul Jain
**Div:** Q
**Batch:** Q1
**Assignment No:** 3 **Date:** 06/11/2026

**Title / Problem Statement:** Vehicle Management System ka program likhna jo different types of vehicles ki details store kare. Base class Vehicle ho, Car, Truck, Motorcycle aur ElectricVehicle usse derive hon, aur ElectricVehicle mein Battery class ke saath multiple inheritance use ho. Single aur multiple inheritance dono dikhane hain.

**Theory:**

*Classes aur Objects:* Class ek blueprint hoti hai jisme data (members) aur functions (methods) define hote hain. Object us class ka instance hota hai. Syntax: `class Vehicle { ... };`. Is program mein Vehicle class common details (vehicle number, brand, model, engine power) rakhti hai, aur `Car car(...);` jaise statements se objects banaye jaate hain.

*Constructors aur Member Initializer List:* Constructor object banate waqt apne aap call hota hai aur data set karta hai. Is program mein constructors mein `: Vehicle(vn, b, m, ep)` jaisi initializer list use hui hai, jisse base class ka data sahi tarike se set hota hai.

*Single Inheritance:* Ek derived class sirf ek base class se inherit karti hai. Syntax: `class Car : public Vehicle { ... };`. Car, Truck aur Motorcycle isi tarah Vehicle se inherit karti hain, aur har class apni extra details (seats, payload, cc) add karti hai.

*Multiple Inheritance:* Ek class ek se zyada base classes se inherit kar sakti hai. Syntax: `class ElectricVehicle : public Vehicle, public Battery { ... };`. ElectricVehicle ko vehicle ki details bhi chahiye aur battery ki bhi, isliye dono classes se inherit kiya gaya hai.

*Virtual Functions aur Polymorphism:* Base class mein `virtual void display() const` declare kiya hai, aur derived classes mein `override` ke saath alag implementation hai. Isse Vehicle pointer ke through call karne par bhi sahi class ka display function chalta hai. Program mein `vector<Vehicle*>` isi ke liye use hua hai.

*Access Specifiers:* `protected` members base class mein hain taaki derived classes unhe access kar sakein, aur `public` se bahar ke functions ko interface milta hai.

*Virtual Destructor:* Base class ka destructor `virtual` rakha hai, taaki pointer ke through delete karne par derived class ka destructor bhi chale.

**Algorithm:**

1. Vehicle base class define karo jisme vehicleNumber, brand, model, enginePower store hon.
2. Vehicle ka constructor aur `display()` function likho.
3. Car, Truck, Motorcycle ko Vehicle se public inheritance se derive karo aur har ek ke extra fields aur display function add karo.
4. Battery class banao jisme capacity, voltage aur battery type ho.
5. ElectricVehicle ko Vehicle aur Battery dono se inherit karwao, range add karo, aur display function mein dono ki details dikhao.
6. main() mein har type ka object banao aur display call karo.
7. Vehicle pointers ka vector banao aur loop chala kar sab vehicles ki details print karo.

**Input:** Har vehicle ki details program ke andar hi di gayi hain. Vehicle Number, Brand, Model, Engine Power aur type-specific values (seats, payload, engine cc, battery details, range).

**Output:** Har vehicle ki details alag-alag block mein print hoti hain. Car ke liye seats, Truck ke liye payload, Motorcycle ke liye engine capacity aur ElectricVehicle ke liye battery details aur range dikhte hain. Phir same vehicles ko base class pointer se loop karke bhi print kiya jaata hai, aur wahi output aata hai.

**Conclusion:** Is assignment se single inheritance aur multiple inheritance dono ka use samajh aaya. Base class ke members derived classes mein kaam aate hain, aur ElectricVehicle mein Vehicle aur Battery dono ko combine karke multiple inheritance dikhaya gaya. Virtual function ki wajah se base pointer ke through bhi sahi display call hota hai.

---

**Program:** (Source code alag file mein hai: `vehicle_management.cpp`. Output ke liye `sample_output.txt` dekh sakte ho.)
